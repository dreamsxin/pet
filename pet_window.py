from __future__ import annotations

import ctypes
from dataclasses import dataclass
import logging
import math
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

from image_pipeline import PetFrame


SPI_GETWORKAREA = 48
FOLLOW_INTERVAL_MS = 120
MIN_WINDOW_EDGE = 80
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
LOGGER = logging.getLogger("pet.window")


class Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


@dataclass(slots=True)
class WindowAttachment:
    hwnd: int
    edge: str
    offset: int


class PetWindow:
    def __init__(
        self,
        root: tk.Tk,
        frames: list[PetFrame],
        *,
        edge_padding: int = 24,
        snap_threshold: int = 72,
        window_snap_threshold: int = 160,
        drag_threshold: int = 6,
    ) -> None:
        if not frames:
            raise ValueError("PetWindow requires at least one frame.")

        self.root = root
        self.frames = frames
        self.edge_padding = edge_padding
        self.snap_threshold = snap_threshold
        self.window_snap_threshold = window_snap_threshold
        self.drag_threshold = drag_threshold

        self.current_index = 0
        self.topmost = True
        self.is_dragging = False
        self.attached_window: WindowAttachment | None = None
        self.topmost_var = tk.BooleanVar(value=self.topmost)
        self.drag_origin_x = 0
        self.drag_origin_y = 0
        self.window_origin_x = 0
        self.window_origin_y = 0

        self.frame_width = max(frame.width for frame in frames)
        self.frame_height = max(frame.height for frame in frames)

        self.label = tk.Label(root, bd=0, highlightthickness=0, bg="white", cursor="hand2")
        self.label.pack()

        self.menu = tk.Menu(root, tearoff=False)
        self.menu.add_checkbutton(
            label="置顶",
            onvalue=True,
            offvalue=False,
            variable=self.topmost_var,
            command=self.toggle_topmost,
        )
        self.menu.add_command(label="取消窗体吸附", command=self.detach_window, state="disabled")
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.root.destroy)

        self._configure_window()
        self._bind_events()
        self.show_frame(0)
        self._position_at_bottom_right()
        LOGGER.info(
            "Pet window ready: size=%sx%s edge_padding=%s snap_threshold=%s window_snap_threshold=%s drag_threshold=%s.",
            self.frame_width,
            self.frame_height,
            self.edge_padding,
            self.snap_threshold,
            self.window_snap_threshold,
            self.drag_threshold,
        )
        self.root.after(FOLLOW_INTERVAL_MS, self._follow_attached_window)

    def _get_work_area(self) -> tuple[int, int, int, int]:
        rect = Rect()
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        return rect.left, rect.top, rect.right, rect.bottom

    def _get_window_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        if not ctypes.windll.user32.IsWindow(hwnd):
            return None

        rect = Rect()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None

        return rect.left, rect.top, rect.right, rect.bottom

    def _clamp(self, value: int, lower: int, upper: int) -> int:
        if upper < lower:
            return lower
        return min(max(value, lower), upper)

    def _is_candidate_window(self, hwnd: int) -> bool:
        if hwnd == self.root.winfo_id():
            return False
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return False
        if ctypes.windll.user32.IsIconic(hwnd):
            return False

        ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex_style & WS_EX_TOOLWINDOW:
            return False
        if ex_style & WS_EX_NOACTIVATE:
            return False

        rect = self._get_window_rect(hwnd)
        if rect is None:
            return False

        left, top, right, bottom = rect
        if right - left < MIN_WINDOW_EDGE or bottom - top < MIN_WINDOW_EDGE:
            return False

        if left == 0 and top == 0 and right <= 1 and bottom <= 1:
            return False

        return True

    def _list_candidate_windows(self) -> list[int]:
        candidates: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd: int, l_param: int) -> bool:
            if self._is_candidate_window(hwnd):
                candidates.append(hwnd)
            return True

        ctypes.windll.user32.EnumWindows(callback_type(callback), 0)
        LOGGER.debug("Enumerated %s candidate window(s).", len(candidates))
        return candidates

    def _get_window_title(self, hwnd: int) -> str:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        return title or "<untitled>"

    def _candidate_positions_for_window(
        self,
        rect: tuple[int, int, int, int],
        current_x: int,
        current_y: int,
    ) -> list[tuple[str, int, int, int]]:
        left, top, right, bottom = rect
        work_left, work_top, work_right, work_bottom = self._get_work_area()
        max_window_x = max(left, right - self.frame_width)
        max_window_y = max(top, bottom - self.frame_height)

        positions = [
            ("left", left - self.frame_width, self._clamp(current_y, top, max_window_y), self._clamp(current_y, top, max_window_y) - top),
            ("right", right, self._clamp(current_y, top, max_window_y), self._clamp(current_y, top, max_window_y) - top),
            ("top", self._clamp(current_x, left, max_window_x), top - self.frame_height, self._clamp(current_x, left, max_window_x) - left),
            ("bottom", self._clamp(current_x, left, max_window_x), bottom, self._clamp(current_x, left, max_window_x) - left),
        ]

        visible_positions: list[tuple[str, int, int, int]] = []
        for edge, candidate_x, candidate_y, offset in positions:
            if candidate_x < work_left or candidate_y < work_top:
                continue
            if candidate_x + self.frame_width > work_right or candidate_y + self.frame_height > work_bottom:
                continue
            visible_positions.append((edge, candidate_x, candidate_y, offset))

        return visible_positions

    def _find_window_attachment(self, current_x: int, current_y: int) -> tuple[WindowAttachment, int, int] | None:
        best_match: tuple[WindowAttachment, int, int, float] | None = None
        nearest_candidate: tuple[int, str, int, int, int, float] | None = None
        candidates = self._list_candidate_windows()
        LOGGER.info("Checking window attachment at (%s, %s), candidates=%s.", current_x, current_y, len(candidates))

        for hwnd in candidates:
            rect = self._get_window_rect(hwnd)
            if rect is None:
                continue

            for edge, candidate_x, candidate_y, offset in self._candidate_positions_for_window(rect, current_x, current_y):
                distance = math.hypot(candidate_x - current_x, candidate_y - current_y)
                if nearest_candidate is None or distance < nearest_candidate[5]:
                    nearest_candidate = (hwnd, edge, candidate_x, candidate_y, offset, distance)
                if distance > self.window_snap_threshold:
                    continue

                attachment = WindowAttachment(hwnd=hwnd, edge=edge, offset=offset)
                LOGGER.info(
                    "Window snap candidate: hwnd=%s title=%s edge=%s target=(%s, %s) distance=%.1f offset=%s.",
                    hwnd,
                    self._get_window_title(hwnd),
                    edge,
                    candidate_x,
                    candidate_y,
                    distance,
                    offset,
                )
                if best_match is None or distance < best_match[3]:
                    best_match = (attachment, candidate_x, candidate_y, distance)

        if best_match is None:
            if nearest_candidate is None:
                LOGGER.info("No window attachment matched within threshold=%s, and no visible edge target was available.", self.window_snap_threshold)
            else:
                hwnd, edge, candidate_x, candidate_y, offset, distance = nearest_candidate
                LOGGER.info(
                    "No window attachment matched within threshold=%s. Nearest candidate: hwnd=%s title=%s edge=%s target=(%s, %s) distance=%.1f offset=%s.",
                    self.window_snap_threshold,
                    hwnd,
                    self._get_window_title(hwnd),
                    edge,
                    candidate_x,
                    candidate_y,
                    distance,
                    offset,
                )
            return None

        attachment, candidate_x, candidate_y, _ = best_match
        LOGGER.info(
            "Window attachment selected: hwnd=%s title=%s edge=%s target=(%s, %s) offset=%s.",
            attachment.hwnd,
            self._get_window_title(attachment.hwnd),
            attachment.edge,
            candidate_x,
            candidate_y,
            attachment.offset,
        )
        return attachment, candidate_x, candidate_y

    def _position_for_attachment(
        self,
        attachment: WindowAttachment,
        rect: tuple[int, int, int, int],
    ) -> tuple[int, int]:
        left, top, right, bottom = rect

        if attachment.edge in {"left", "right"}:
            max_y = max(top, bottom - self.frame_height)
            y_pos = self._clamp(top + attachment.offset, top, max_y)
            x_pos = left - self.frame_width if attachment.edge == "left" else right
            return x_pos, y_pos

        max_x = max(left, right - self.frame_width)
        x_pos = self._clamp(left + attachment.offset, left, max_x)
        y_pos = top - self.frame_height if attachment.edge == "top" else bottom
        return x_pos, y_pos

    def _set_attachment(self, attachment: WindowAttachment | None) -> None:
        self.attached_window = attachment
        state = "normal" if attachment else "disabled"
        self.menu.entryconfigure("取消窗体吸附", state=state)
        if attachment is None:
            LOGGER.info("Detached from window.")
        else:
            LOGGER.info(
                "Attached to window: hwnd=%s title=%s edge=%s offset=%s.",
                attachment.hwnd,
                self._get_window_title(attachment.hwnd),
                attachment.edge,
                attachment.offset,
            )

    def _configure_window(self) -> None:
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.topmost)
        self.root.configure(bg="white")
        self.root.wm_attributes("-transparentcolor", "white")
        self.root.geometry(f"{self.frame_width}x{self.frame_height}")

    def _bind_events(self) -> None:
        self.label.bind("<ButtonPress-1>", self.start_drag)
        self.label.bind("<Button-3>", self.show_context_menu)

    def _position_at_bottom_right(self) -> None:
        left, top, right, bottom = self._get_work_area()
        x_pos = max(left, right - self.frame_width - self.edge_padding)
        y_pos = max(top, bottom - self.frame_height - self.edge_padding)
        self.root.geometry(f"{self.frame_width}x{self.frame_height}+{x_pos}+{y_pos}")
        LOGGER.info("Initial position set to (%s, %s) within work area (%s, %s, %s, %s).", x_pos, y_pos, left, top, right, bottom)

    def show_frame(self, index: int) -> None:
        self.current_index = index % len(self.frames)
        frame = self.frames[self.current_index]
        self.label.configure(image=frame.image)
        self.label.image = frame.image
        LOGGER.info("Showing frame #%s (%s).", self.current_index, Path(frame.path).name)

    def next_frame(self) -> None:
        self.show_frame(self.current_index + 1)

    def start_drag(self, event) -> None:
        if self.attached_window is not None:
            self.detach_window()

        self.root.grab_set()
        self.root.bind("<B1-Motion>", self.on_drag)
        self.root.bind("<ButtonRelease-1>", self.end_drag)
        self.drag_origin_x = event.x_root
        self.drag_origin_y = event.y_root
        self.window_origin_x = self.root.winfo_x()
        self.window_origin_y = self.root.winfo_y()
        self.is_dragging = False
        LOGGER.info(
            "Pointer down: pointer=(%s, %s) window_origin=(%s, %s).",
            self.drag_origin_x,
            self.drag_origin_y,
            self.window_origin_x,
            self.window_origin_y,
        )

    def on_drag(self, event) -> None:
        delta_x = event.x_root - self.drag_origin_x
        delta_y = event.y_root - self.drag_origin_y

        if not self.is_dragging and math.hypot(delta_x, delta_y) > self.drag_threshold:
            self.is_dragging = True
            LOGGER.info(
                "Drag started: delta=(%s, %s) threshold=%s.",
                delta_x,
                delta_y,
                self.drag_threshold,
            )

        if not self.is_dragging:
            return

        next_x = self.window_origin_x + delta_x
        next_y = self.window_origin_y + delta_y
        self.root.geometry(f"+{next_x}+{next_y}")
        LOGGER.debug("Dragging window to (%s, %s).", next_x, next_y)

    def end_drag(self, event) -> None:
        try:
            self.root.grab_release()
        except tk.TclError:
            pass

        self.root.unbind("<B1-Motion>")
        self.root.unbind("<ButtonRelease-1>")

        if self.is_dragging:
            LOGGER.info("Drag ended at (%s, %s).", self.root.winfo_x(), self.root.winfo_y())
            attachment = self._find_window_attachment(self.root.winfo_x(), self.root.winfo_y())
            if attachment is not None:
                self._set_attachment(attachment[0])
                self.root.geometry(f"+{attachment[1]}+{attachment[2]}")
                LOGGER.info("Moved to attached window target (%s, %s).", attachment[1], attachment[2])
                self.is_dragging = False
                return

            self.snap_to_edge()
            self.is_dragging = False
            return

        LOGGER.info("Click detected, switching to next frame.")
        self.next_frame()

    def snap_to_edge(self) -> None:
        left, top, right, bottom = self._get_work_area()

        current_x = self.root.winfo_x()
        current_y = self.root.winfo_y()

        max_x = max(left, right - self.frame_width)
        max_y = max(top, bottom - self.frame_height)

        clamped_x = min(max(current_x, left), max_x)
        clamped_y = min(max(current_y, top), max_y)

        distances = {
            "left": clamped_x - left,
            "right": max_x - clamped_x,
            "top": clamped_y - top,
            "bottom": max_y - clamped_y,
        }
        nearest_edge = min(distances, key=distances.get)
        LOGGER.info(
            "Screen edge snap check: position=(%s, %s) nearest_edge=%s distance=%s threshold=%s.",
            clamped_x,
            clamped_y,
            nearest_edge,
            distances[nearest_edge],
            self.snap_threshold,
        )

        if distances[nearest_edge] <= self.snap_threshold:
            if nearest_edge == "left":
                clamped_x = left
            elif nearest_edge == "right":
                clamped_x = max_x
            elif nearest_edge == "top":
                clamped_y = top
            elif nearest_edge == "bottom":
                clamped_y = max_y
        else:
            LOGGER.info("Screen edge snap skipped because distance %.1f exceeded threshold %s.", distances[nearest_edge], self.snap_threshold)

        self.root.geometry(f"+{clamped_x}+{clamped_y}")
        LOGGER.info("Screen edge snap result: moved_to=(%s, %s).", clamped_x, clamped_y)

    def toggle_topmost(self) -> None:
        self.topmost = self.topmost_var.get()
        self.root.attributes("-topmost", self.topmost)
        LOGGER.info("Topmost changed: %s.", self.topmost)

    def detach_window(self) -> None:
        self._set_attachment(None)

    def _follow_attached_window(self) -> None:
        try:
            if self.attached_window is not None:
                rect = self._get_window_rect(self.attached_window.hwnd)
                if rect is None or ctypes.windll.user32.IsIconic(self.attached_window.hwnd):
                    LOGGER.info("Attached window is unavailable or minimized, detaching.")
                    self.detach_window()
                else:
                    positions = self._candidate_positions_for_window(rect, self.root.winfo_x(), self.root.winfo_y())
                    matching = next((item for item in positions if item[0] == self.attached_window.edge), None)
                    if matching is None:
                        LOGGER.info("Attached window edge is no longer visible in work area, detaching.")
                        self.detach_window()
                    else:
                        next_x, next_y = self._position_for_attachment(self.attached_window, rect)
                        self.root.geometry(f"+{next_x}+{next_y}")
                        LOGGER.debug(
                            "Following window: hwnd=%s title=%s edge=%s moved_to=(%s, %s).",
                            self.attached_window.hwnd,
                            self._get_window_title(self.attached_window.hwnd),
                            self.attached_window.edge,
                            next_x,
                            next_y,
                        )
        finally:
            try:
                self.root.after(FOLLOW_INTERVAL_MS, self._follow_attached_window)
            except tk.TclError:
                pass

    def show_context_menu(self, event) -> None:
        LOGGER.info("Showing context menu at (%s, %s).", event.x_root, event.y_root)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
