from __future__ import annotations

import argparse
import ctypes
import json
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


SPI_GETWORKAREA = 48
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
MIN_WINDOW_EDGE = 80
LOG_PREFIX = "[window_bridge]"
BRIDGE_VERSION = 2
GA_ROOT = 2


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


def parse_optional_int(value: str) -> int | None:
    if value in {"", "null", "None"}:
        return None
    try:
        return int(value)
    except ValueError:
        return int(float(value))


class Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def get_work_area() -> tuple[int, int, int, int]:
    rect = Rect()
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return rect.left, rect.top, rect.right, rect.bottom


def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not ctypes.windll.user32.IsWindow(hwnd):
        return None
    rect = Rect()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def get_window_pid(hwnd: int) -> int:
    process_id = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return int(process_id.value)


def get_window_title(hwnd: int) -> str:
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
    title = buffer.value.strip()
    return title or "<untitled>"


def get_root_window(hwnd: int) -> int:
    return int(ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT))


def find_top_level_window_by_pid(pid: int) -> int | None:
    matches: list[tuple[int, int]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _l_param: int) -> bool:
        if get_window_pid(hwnd) != pid:
            return True
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        rect = get_window_rect(hwnd)
        if rect is None:
            return True
        left, top, right, bottom = rect
        area = max(0, right - left) * max(0, bottom - top)
        matches.append((hwnd, area))
        return True

    ctypes.windll.user32.EnumWindows(callback_type(callback), 0)
    if not matches:
        return None
    matches.sort(key=lambda item: item[1], reverse=True)
    return matches[0][0]


def top_window_at_point(pointer_x: int, pointer_y: int, exclude_pid: int | None = None) -> int | None:
    point = POINT(pointer_x, pointer_y)
    hwnd = int(ctypes.windll.user32.WindowFromPoint(point))
    while hwnd:
        root = get_root_window(hwnd)
        if root == 0:
            break
        if is_candidate_window(root, exclude_pid):
            return root
        hwnd = int(ctypes.windll.user32.GetParent(root))
    return None


def clamp(value: int, lower: int, upper: int) -> int:
    if upper < lower:
        return lower
    return min(max(value, lower), upper)


def rect_to_payload(rect: tuple[int, int, int, int] | None) -> dict | None:
    if rect is None:
        return None
    return {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]}


def map_point_from_physical(
    x_pos: int,
    y_pos: int,
    physical_rect: tuple[int, int, int, int] | None,
    logical_rect: tuple[int, int, int, int],
) -> tuple[int, int]:
    if physical_rect is None:
        return x_pos, y_pos
    physical_left, physical_top, physical_right, physical_bottom = physical_rect
    logical_left, logical_top, logical_right, logical_bottom = logical_rect
    physical_width = physical_right - physical_left
    physical_height = physical_bottom - physical_top
    logical_width = logical_right - logical_left
    logical_height = logical_bottom - logical_top
    if physical_width <= 0 or physical_height <= 0:
        return x_pos, y_pos
    logical_x = logical_left + round((x_pos - physical_left) * logical_width / physical_width)
    logical_y = logical_top + round((y_pos - physical_top) * logical_height / physical_height)
    return logical_x, logical_y


def map_anchor_to_physical(
    anchors: dict[str, tuple[int, int]],
    physical_rect: tuple[int, int, int, int],
    logical_rect: tuple[int, int, int, int],
) -> dict[str, tuple[int, int]]:
    physical_width = physical_rect[2] - physical_rect[0]
    physical_height = physical_rect[3] - physical_rect[1]
    logical_width = logical_rect[2] - logical_rect[0]
    logical_height = logical_rect[3] - logical_rect[1]
    if logical_width <= 0 or logical_height <= 0:
        return anchors
    return {
        edge: (
            round(anchor[0] * physical_width / logical_width),
            round(anchor[1] * physical_height / logical_height),
        )
        for edge, anchor in anchors.items()
    }


def overlap_area(
    rect_a: tuple[int, int, int, int],
    rect_b: tuple[int, int, int, int],
) -> int:
    left = max(rect_a[0], rect_b[0])
    top = max(rect_a[1], rect_b[1])
    right = min(rect_a[2], rect_b[2])
    bottom = min(rect_a[3], rect_b[3])
    if right <= left or bottom <= top:
        return 0
    return (right - left) * (bottom - top)


def top_slot_positions(left: int, right: int, pet_width: int) -> list[int]:
    max_x = max(left, right - pet_width)
    center_x = left + max(0, (max_x - left) // 2)
    return [left, center_x, max_x]


def is_candidate_window(hwnd: int, exclude_pid: int | None = None) -> bool:
    if not ctypes.windll.user32.IsWindowVisible(hwnd):
        return False
    if ctypes.windll.user32.IsIconic(hwnd):
        return False
    if exclude_pid is not None and get_window_pid(hwnd) == exclude_pid:
        return False
    ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if ex_style & WS_EX_TOOLWINDOW:
        return False
    if ex_style & WS_EX_NOACTIVATE:
        return False
    rect = get_window_rect(hwnd)
    if rect is None:
        return False
    left, top, right, bottom = rect
    if right - left < MIN_WINDOW_EDGE or bottom - top < MIN_WINDOW_EDGE:
        return False
    if left == 0 and top == 0 and right <= 1 and bottom <= 1:
        return False
    return True


def list_candidate_windows(exclude_pid: int | None = None) -> list[int]:
    results: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _l_param: int) -> bool:
        if is_candidate_window(hwnd, exclude_pid):
            results.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(callback_type(callback), 0)
    return results


def candidate_positions_for_window(
    rect: tuple[int, int, int, int],
    current_x: int,
    current_y: int,
    pet_width: int,
    pet_height: int,
    anchors: dict[str, tuple[int, int]],
) -> list[tuple[str, int, int, int, int | None]]:
    left, top, right, bottom = rect
    work_left, work_top, work_right, work_bottom = get_work_area()
    left_anchor_x, left_anchor_y = anchors["left"]
    right_anchor_x, right_anchor_y = anchors["right"]
    top_anchor_x, top_anchor_y = anchors["top"]
    bottom_anchor_x, bottom_anchor_y = anchors["bottom"]

    max_contact_x = right
    min_contact_x = left
    max_contact_y = bottom
    min_contact_y = top

    current_left_contact_y = current_y + left_anchor_y
    current_right_contact_y = current_y + right_anchor_y
    current_top_contact_x = current_x + top_anchor_x
    current_bottom_contact_x = current_x + bottom_anchor_x

    left_contact_y = clamp(current_left_contact_y, min_contact_y, max_contact_y)
    right_contact_y = clamp(current_right_contact_y, min_contact_y, max_contact_y)
    top_contact_x = clamp(current_top_contact_x, min_contact_x, max_contact_x)
    bottom_contact_x = clamp(current_bottom_contact_x, min_contact_x, max_contact_x)

    top_slot = min(
        range(3),
        key=lambda index: abs(top_slot_positions(left, right, pet_width)[index] - current_top_contact_x),
    )
    top_contact_positions = top_slot_positions(left, right, pet_width)
    positions = [
        ("left", left - left_anchor_x, left_contact_y - left_anchor_y, left_contact_y - top, None),
        ("right", right - right_anchor_x, right_contact_y - right_anchor_y, right_contact_y - top, None),
        ("top", top_contact_positions[top_slot] - top_anchor_x, top - top_anchor_y, top_contact_x - left, top_slot),
        ("bottom", bottom_contact_x - bottom_anchor_x, bottom - bottom_anchor_y, bottom_contact_x - left, None),
    ]

    visible: list[tuple[str, int, int, int, int | None]] = []
    for edge, x_pos, y_pos, offset, slot in positions:
        if x_pos < work_left or y_pos < work_top:
            continue
        if x_pos + pet_width > work_right or y_pos + pet_height > work_bottom:
            continue
        visible.append((edge, x_pos, y_pos, offset, slot))
    return visible


def edge_contact_distance(
    edge: str,
    pet_rect: tuple[int, int, int, int],
    target_rect: tuple[int, int, int, int],
) -> int:
    pet_left, pet_top, pet_right, pet_bottom = pet_rect
    left, top, right, bottom = target_rect
    if edge == "left":
        outside_distance = abs(pet_right - left) if pet_right <= left else abs(pet_left - left)
        vertical_gap = max(top - pet_bottom, pet_top - bottom, 0)
        return outside_distance + vertical_gap
    if edge == "right":
        outside_distance = abs(pet_left - right) if pet_left >= right else abs(pet_right - right)
        vertical_gap = max(top - pet_bottom, pet_top - bottom, 0)
        return outside_distance + vertical_gap
    if edge == "top":
        outside_distance = abs(pet_bottom - top) if pet_bottom <= top else abs(pet_top - top)
        horizontal_gap = max(left - pet_right, pet_left - right, 0)
        return outside_distance + horizontal_gap
    outside_distance = abs(pet_top - bottom) if pet_top >= bottom else abs(pet_bottom - bottom)
    horizontal_gap = max(left - pet_right, pet_left - right, 0)
    return outside_distance + horizontal_gap


def position_for_attachment(
    rect: tuple[int, int, int, int],
    edge: str,
    offset: int,
    pet_width: int,
    pet_height: int,
    top_slot: int | None,
    anchors: dict[str, tuple[int, int]],
) -> tuple[int, int]:
    left, top, right, bottom = rect
    anchor_x, anchor_y = anchors[edge]
    if edge in {"left", "right"}:
        contact_y = clamp(top + offset, top, bottom)
        y_pos = contact_y - anchor_y
        x_pos = (left if edge == "left" else right) - anchor_x
        return x_pos, y_pos
    if edge == "top" and top_slot is not None:
        return top_slot_positions(left, right, pet_width)[clamp(top_slot, 0, 2)] - anchor_x, top - anchor_y
    contact_x = clamp(left + offset, left, right)
    x_pos = contact_x - anchor_x
    y_pos = (top if edge == "top" else bottom) - anchor_y
    return x_pos, y_pos


def find_nearest_attachment(
    current_x: int,
    current_y: int,
    pet_width: int,
    pet_height: int,
    threshold: int,
    pointer_x: int | None = None,
    pointer_y: int | None = None,
    exclude_pid: int | None = None,
    anchors: dict[str, tuple[int, int]] | None = None,
) -> dict:
    if anchors is None:
        anchors = {
            "left": (pet_width, pet_height // 2),
            "right": (0, pet_height // 2),
            "top": (pet_width // 2, pet_height),
            "bottom": (pet_width // 2, 0),
        }
    logical_rect = (current_x, current_y, current_x + pet_width, current_y + pet_height)
    self_rect = None
    if exclude_pid is not None:
        self_hwnd = find_top_level_window_by_pid(exclude_pid)
        if self_hwnd is not None:
            self_rect = get_window_rect(self_hwnd)
    physical_rect = self_rect if self_rect is not None else logical_rect
    physical_x, physical_y, physical_right, physical_bottom = physical_rect
    physical_width = physical_right - physical_x
    physical_height = physical_bottom - physical_y
    pet_rect = physical_rect
    physical_anchors = map_anchor_to_physical(anchors, physical_rect, logical_rect)

    best: dict | None = None
    nearest_payload: dict | None = None
    candidate_count = 0
    candidate_hwnds: list[int]
    if pointer_x is not None and pointer_y is not None:
        top_hwnd = top_window_at_point(pointer_x, pointer_y, exclude_pid)
        if top_hwnd is not None:
            candidate_hwnds = [top_hwnd]
        else:
            candidate_hwnds = list_candidate_windows(exclude_pid)
    else:
        candidate_hwnds = list_candidate_windows(exclude_pid)

    for hwnd in candidate_hwnds:
        rect = get_window_rect(hwnd)
        if rect is None:
            continue
        candidate_count += 1
        left, top, right, bottom = rect
        overlap = overlap_area(pet_rect, rect)
        pointer_inside = (
            pointer_x is not None
            and pointer_y is not None
            and left <= pointer_x <= right
            and top <= pointer_y <= bottom
        )
        edge_distances = {
            "left": edge_contact_distance("left", pet_rect, rect),
            "right": edge_contact_distance("right", pet_rect, rect),
            "top": edge_contact_distance("top", pet_rect, rect),
            "bottom": edge_contact_distance("bottom", pet_rect, rect),
        }
        for edge, target_x, target_y, offset, top_slot in candidate_positions_for_window(
            rect, physical_x, physical_y, physical_width, physical_height, physical_anchors
        ):
            logical_target_x, logical_target_y = map_point_from_physical(
                target_x,
                target_y,
                self_rect,
                logical_rect,
            )
            distance = edge_distances[edge]
            candidate = {
                "hwnd": hwnd,
                "title": get_window_title(hwnd),
                "edge": edge,
                "offset": offset,
                "top_slot": top_slot,
                "target": {"x": logical_target_x, "y": logical_target_y},
                "physical_target": {"x": target_x, "y": target_y},
                "distance": distance,
                "edge_distances": edge_distances,
                "physical_anchors": physical_anchors,
                "pointer_inside": pointer_inside,
                "overlap": overlap,
                "rect": {"left": left, "top": top, "right": right, "bottom": bottom},
            }
            if nearest_payload is None or distance < nearest_payload["distance"]:
                nearest_payload = candidate
            if overlap <= 0 and not pointer_inside and distance > threshold:
                continue
            payload = {
                "hwnd": hwnd,
                "title": get_window_title(hwnd),
                "edge": edge,
                "offset": offset,
                "top_slot": top_slot,
                "target": {"x": logical_target_x, "y": logical_target_y},
                "physical_target": {"x": target_x, "y": target_y},
                "distance": distance,
                "edge_distances": edge_distances,
                "physical_anchors": physical_anchors,
                "pointer_inside": pointer_inside,
                "overlap": overlap,
                "rect": {"left": left, "top": top, "right": right, "bottom": bottom},
            }
            if best is None:
                best = payload
            elif overlap > 0 and best.get("overlap", 0) <= 0:
                best = payload
            elif overlap > 0 and best.get("overlap", 0) > 0:
                if overlap > int(best.get("overlap", 0)):
                    best = payload
                elif overlap == int(best.get("overlap", 0)) and distance < best["distance"]:
                    best = payload
            elif pointer_inside and not best.get("pointer_inside", False):
                best = payload
            elif pointer_inside == best.get("pointer_inside", False) and distance < best["distance"]:
                best = payload
    if best is None:
        print(
            f"{LOG_PREFIX} nearest matched=False current=({current_x},{current_y}) "
            f"pointer=({pointer_x},{pointer_y}) threshold={threshold} candidates={candidate_count} self_rect={self_rect} nearest={nearest_payload}",
            flush=True,
        )
        return {
            "bridge_version": BRIDGE_VERSION,
            "matched": False,
            "candidates": candidate_count,
            "self_rect": self_rect,
            "logical_rect": rect_to_payload(logical_rect),
            "physical_rect": rect_to_payload(physical_rect),
            "nearest": nearest_payload,
        }
    print(
        f"{LOG_PREFIX} nearest matched=True current=({current_x},{current_y}) "
        f"pointer=({pointer_x},{pointer_y}) threshold={threshold} candidates={candidate_count} self_rect={self_rect} attachment={best}",
        flush=True,
    )
    return {
        "bridge_version": BRIDGE_VERSION,
        "matched": True,
        "attachment": best,
        "candidates": candidate_count,
        "self_rect": self_rect,
        "logical_rect": rect_to_payload(logical_rect),
        "physical_rect": rect_to_payload(physical_rect),
    }


def follow_attachment(
    hwnd: int,
    edge: str,
    offset: int,
    pet_width: int,
    pet_height: int,
    top_slot: int | None,
    anchors: dict[str, tuple[int, int]] | None = None,
    self_rect: tuple[int, int, int, int] | None = None,
    logical_rect: tuple[int, int, int, int] | None = None,
) -> dict:
    if anchors is None:
        anchors = {
            "left": (pet_width, pet_height // 2),
            "right": (0, pet_height // 2),
            "top": (pet_width // 2, pet_height),
            "bottom": (pet_width // 2, 0),
        }
    rect = get_window_rect(hwnd)
    if rect is None or ctypes.windll.user32.IsIconic(hwnd):
        print(
            f"{LOG_PREFIX} follow available=False hwnd={hwnd} edge={edge} offset={offset} top_slot={top_slot}",
            flush=True,
        )
        return {"bridge_version": BRIDGE_VERSION, "available": False}
    physical_width = pet_width
    physical_height = pet_height
    physical_anchors = anchors
    if self_rect is not None:
        physical_width = self_rect[2] - self_rect[0]
        physical_height = self_rect[3] - self_rect[1]
    if self_rect is not None and logical_rect is not None:
        physical_anchors = map_anchor_to_physical(anchors, self_rect, logical_rect)
    target_x, target_y = position_for_attachment(rect, edge, offset, physical_width, physical_height, top_slot, physical_anchors)
    logical_target_x, logical_target_y = target_x, target_y
    if logical_rect is not None:
        logical_target_x, logical_target_y = map_point_from_physical(target_x, target_y, self_rect, logical_rect)
    print(
        f"{LOG_PREFIX} follow available=True hwnd={hwnd} edge={edge} offset={offset} top_slot={top_slot} "
        f"target=({logical_target_x},{logical_target_y}) physical_target=({target_x},{target_y}) rect={rect} self_rect={self_rect}",
        flush=True,
    )
    return {
        "bridge_version": BRIDGE_VERSION,
        "available": True,
        "target": {"x": logical_target_x, "y": logical_target_y},
        "physical_target": {"x": target_x, "y": target_y},
        "physical_anchors": physical_anchors,
        "self_rect": self_rect,
        "logical_rect": rect_to_payload(logical_rect),
    }


class Handler(BaseHTTPRequestHandler):
    def _write_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        anchors = {
            "left": (int(params.get("anchor_left_x", ["320"])[0]), int(params.get("anchor_left_y", ["160"])[0])),
            "right": (int(params.get("anchor_right_x", ["0"])[0]), int(params.get("anchor_right_y", ["160"])[0])),
            "top": (int(params.get("anchor_top_x", ["160"])[0]), int(params.get("anchor_top_y", ["320"])[0])),
            "bottom": (int(params.get("anchor_bottom_x", ["160"])[0]), int(params.get("anchor_bottom_y", ["0"])[0])),
        }
        if parsed.path == "/nearest":
            pointer_x_raw = params.get("pointer_x", [""])[0]
            pointer_y_raw = params.get("pointer_y", [""])[0]
            response = find_nearest_attachment(
                int(params.get("x", ["0"])[0]),
                int(params.get("y", ["0"])[0]),
                int(params.get("width", ["320"])[0]),
                int(params.get("height", ["320"])[0]),
                int(params.get("threshold", ["160"])[0]),
                int(pointer_x_raw) if pointer_x_raw else None,
                int(pointer_y_raw) if pointer_y_raw else None,
                parse_optional_int(params.get("exclude_pid", [""])[0]),
                anchors,
            )
            self._write_json(response)
            return
        if parsed.path == "/follow":
            top_slot_raw = params.get("top_slot", [""])[0]
            top_slot = parse_optional_int(top_slot_raw)
            logical_x = int(params.get("x", ["0"])[0])
            logical_y = int(params.get("y", ["0"])[0])
            logical_width = int(params.get("width", ["320"])[0])
            logical_height = int(params.get("height", ["320"])[0])
            exclude_pid = parse_optional_int(params.get("exclude_pid", [""])[0])
            self_rect = None
            if exclude_pid is not None:
                self_hwnd = find_top_level_window_by_pid(exclude_pid)
                if self_hwnd is not None:
                    self_rect = get_window_rect(self_hwnd)
            response = follow_attachment(
                int(params.get("hwnd", ["0"])[0]),
                params.get("edge", ["left"])[0],
                int(params.get("offset", ["0"])[0]),
                logical_width,
                logical_height,
                top_slot,
                anchors,
                self_rect,
                (logical_x, logical_y, logical_x + logical_width, logical_y + logical_height),
            )
            self._write_json(response)
            return
        self._write_json({"error": "not_found"}, 404)

    def log_message(self, _format: str, *_args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18992)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"window_bridge listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
