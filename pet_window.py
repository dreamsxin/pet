from __future__ import annotations

import ctypes
from dataclasses import dataclass
import logging
import math
import random
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

from image_pipeline import AtlasFrames, EdgeHideFrames, PetFrame, WindowDockFrames


SPI_GETWORKAREA = 48
FOLLOW_INTERVAL_MS = 120
MIN_WINDOW_EDGE = 80
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
MOVE_INTERVAL_MS = 40
MOVE_MIN_DURATION_MS = 700
MOVE_MAX_DURATION_MS = 1300
MOVE_MS_PER_PIXEL = 1.6
WINDOW_DOCK_OFFSETS = {
    "top": (0, 0),
    "bottom": (0, 0),
    "left": (0, 0),
    "right": (0, 0),
}
WINDOW_DOCK_ORIGIN_RATIOS = {
    "top": (0.5, 0.5),
    "bottom": (0.5, 0.0),
    "left": (1.0, 0.5),
    "right": (0.0, 0.5),
}
WINDOW_DOCK_ORIGIN_PIXELS: dict[str, tuple[int, int] | None] = {
    "top": None,
    "bottom": None,
    "left": None,
    "right": None,
}
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
    top_slot: int | None = None


class PetWindow:
    def __init__(
        self,
        root: tk.Tk,
        frames_by_state: AtlasFrames,
        edge_hide_frames: EdgeHideFrames | None = None,
        window_dock_frames: WindowDockFrames | None = None,
        *,
        edge_padding: int = 24,
        snap_threshold: int = 72,
        window_snap_threshold: int = 160,
        drag_threshold: int = 6,
    ) -> None:
        if not frames_by_state:
            raise ValueError("PetWindow requires at least one frame.")

        self.root = root
        self.frames_by_state = frames_by_state
        self.edge_hide_frames = edge_hide_frames or {}
        self.window_dock_frames = window_dock_frames or {}
        self.edge_padding = edge_padding
        self.snap_threshold = snap_threshold
        self.window_snap_threshold = window_snap_threshold
        self.drag_threshold = drag_threshold

        self.current_state = "idle" if "idle" in frames_by_state else next(iter(frames_by_state))
        self.current_index = 0
        self.topmost = True
        self.is_dragging = False
        self.attached_window: WindowAttachment | None = None
        self.screen_edge_attachment: str | None = None
        self.screen_top_slot: int | None = None
        self.pending_top_slot: int | None = None
        self.top_hop_active = False
        self.topmost_var = tk.BooleanVar(value=self.topmost)
        self.drag_origin_x = 0
        self.drag_origin_y = 0
        self.window_origin_x = 0
        self.window_origin_y = 0
        self.last_pointer_x = 0
        self.last_pointer_y = 0
        self.drag_started_with_window_attachment = False
        self.drag_started_with_screen_attachment = False
        self.drag_restore_state = self.current_state
        self.drag_animation_state: str | None = None
        self.is_hidden_on_edge = False
        self.is_window_dock_pose = False
        self.edge_hide_edge: str | None = None
        self.edge_hide_index = 0
        self.base_x = 0
        self.base_y = 0
        self.offset_x = 0
        self.offset_y = 0

        all_frames = [frame for frames in frames_by_state.values() for frame in frames]
        for frames in self.edge_hide_frames.values():
            all_frames.extend(frames)
        all_frames.extend(self.window_dock_frames.values())
        self.frame_width = max(frame.width for frame in all_frames)
        self.frame_height = max(frame.height for frame in all_frames)
        self.animation_after_id: str | None = None
        self.move_after_id: str | None = None

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
        state_menu = tk.Menu(self.menu, tearoff=False)
        for state_name in self.frames_by_state:
            state_menu.add_command(label=state_name, command=lambda value=state_name: self.set_state(value))
        self.menu.add_cascade(label="切换状态", menu=state_menu)
        self.menu.add_command(label="取消窗体吸附", command=self.detach_window, state="disabled")
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.root.destroy)

        self._configure_window()
        self._bind_events()
        self.set_state(self.current_state)
        self._position_at_bottom_right()
        LOGGER.info(
            "Pet window ready: state=%s size=%sx%s edge_padding=%s snap_threshold=%s window_snap_threshold=%s drag_threshold=%s.",
            self.current_state,
            self.frame_width,
            self.frame_height,
            self.edge_padding,
            self.snap_threshold,
            self.window_snap_threshold,
            self.drag_threshold,
        )
        self.root.after(FOLLOW_INTERVAL_MS, self._follow_attached_window)

    def _exit_edge_hide_mode(self) -> None:
        if not self.is_hidden_on_edge:
            return
        self.is_hidden_on_edge = False
        self.edge_hide_edge = None
        self.edge_hide_index = 0
        LOGGER.info("Exited edge-hide mode.")

    def _exit_window_dock_pose(self) -> None:
        if not self.is_window_dock_pose:
            return
        self.is_window_dock_pose = False
        LOGGER.info("Exited window-dock pose mode.")

    def _enter_window_dock_pose(self, edge: str) -> None:
        if edge not in self.window_dock_frames:
            LOGGER.info("No window-dock image configured for edge=%s.", edge)
            self._exit_window_dock_pose()
            return
        self._exit_edge_hide_mode()
        self.is_window_dock_pose = True
        frame = self.window_dock_frames[edge]
        self.label.configure(image=frame.image)
        self.label.image = frame.image
        LOGGER.info("Entered window-dock pose for edge=%s (%s).", edge, Path(frame.path).name)

    def _enter_edge_hide_mode(self, edge: str) -> None:
        if edge not in self.edge_hide_frames:
            LOGGER.info("No edge-hide image configured for edge=%s.", edge)
            self._exit_edge_hide_mode()
            return
        self._exit_window_dock_pose()
        self.is_hidden_on_edge = True
        self.edge_hide_edge = edge
        self.edge_hide_index = 0
        frame = self.edge_hide_frames[edge][self.edge_hide_index]
        self.label.configure(image=frame.image)
        self.label.image = frame.image
        LOGGER.info("Entered edge-hide mode for edge=%s (%s).", edge, Path(frame.path).name)
        self._schedule_next_frame()

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

    def _clear_screen_attachment(self) -> None:
        self.screen_edge_attachment = None
        self.screen_top_slot = None
        self.pending_top_slot = None

    def _apply_geometry(self) -> None:
        final_x = self.base_x + self.offset_x
        final_y = self.base_y + self.offset_y
        self.root.geometry(f"{self.frame_width}x{self.frame_height}+{final_x}+{final_y}")

    def _set_base_position(self, x_pos: int, y_pos: int) -> None:
        self.base_x = x_pos
        self.base_y = y_pos
        LOGGER.info("Base position set: base=(%s, %s) offset=(%s, %s).", self.base_x, self.base_y, self.offset_x, self.offset_y)
        self._apply_geometry()

    def _set_motion_offset(self, x_offset: int, y_offset: int = 0) -> None:
        self.offset_x = x_offset
        self.offset_y = y_offset
        LOGGER.info(
            "Motion offset set: base=(%s, %s) offset=(%s, %s) actual=(%s, %s).",
            self.base_x,
            self.base_y,
            self.offset_x,
            self.offset_y,
            self.base_x + self.offset_x,
            self.base_y + self.offset_y,
        )
        self._apply_geometry()

    def _top_slot_positions(self, left: int, right: int) -> list[int]:
        max_x = max(left, right - self.frame_width)
        center_x = left + max(0, (max_x - left) // 2)
        return [left, center_x, max_x]

    def _window_dock_origin(self, edge: str) -> tuple[int, int]:
        frame = self.window_dock_frames.get(edge)
        if frame is None:
            return 0, 0

        override = WINDOW_DOCK_ORIGIN_PIXELS.get(edge)
        if override is not None:
            return override

        ratio_x, ratio_y = WINDOW_DOCK_ORIGIN_RATIOS.get(edge, (0.0, 0.0))
        origin_x = round(frame.width * ratio_x)
        origin_y = round(frame.height * ratio_y)
        origin_x = self._clamp(origin_x, 0, frame.width)
        origin_y = self._clamp(origin_y, 0, frame.height)
        return origin_x, origin_y

    def _window_dock_offsets(self, edge: str) -> tuple[int, int]:
        return WINDOW_DOCK_OFFSETS.get(edge, (0, 0))

    def _window_dock_contact_x_bounds(
        self,
        rect: tuple[int, int, int, int],
        origin_x: int,
    ) -> tuple[int, int]:
        left, _top, right, _bottom = rect
        work_left, _work_top, work_right, _work_bottom = self._get_work_area()
        lower = max(left, work_left + origin_x)
        upper = min(right, work_right - self.frame_width + origin_x)
        return lower, upper

    def _window_dock_contact_y_bounds(
        self,
        rect: tuple[int, int, int, int],
        origin_y: int,
    ) -> tuple[int, int]:
        _left, top, _right, bottom = rect
        _work_left, work_top, _work_right, work_bottom = self._get_work_area()
        lower = max(top, work_top + origin_y)
        upper = min(bottom, work_bottom - self.frame_height + origin_y)
        return lower, upper

    def _screen_edge_distances(self) -> dict[str, int]:
        left, top, right, bottom = self._get_work_area()
        pointer_x = self.last_pointer_x or self.root.winfo_x()
        pointer_y = self.last_pointer_y or self.root.winfo_y()
        return {
            "left": abs(pointer_x - left),
            "right": abs(right - pointer_x),
            "top": abs(pointer_y - top),
            "bottom": abs(bottom - pointer_y),
        }

    def _screen_edge_candidate(self) -> str | None:
        distances = self._screen_edge_distances()
        nearest_edge = min(distances, key=distances.get)
        if distances[nearest_edge] <= self.snap_threshold:
            return nearest_edge
        return None

    def _nearest_top_slot(self, current_x: int, left: int, right: int) -> tuple[int, int]:
        positions = self._top_slot_positions(left, right)
        slot_index = min(range(len(positions)), key=lambda index: abs(positions[index] - current_x))
        return slot_index, positions[slot_index]

    def _plan_top_slot_transition(self, current_slot: int) -> tuple[int, int | None]:
        if current_slot == 0:
            return 1, 2
        if current_slot == 2:
            return 1, 0
        if self.pending_top_slot is not None:
            return self.pending_top_slot, None
        return random.choice([0, 2]), None

    def _cancel_move_animation(self) -> None:
        if self.move_after_id is None:
            return
        try:
            self.root.after_cancel(self.move_after_id)
        except tk.TclError:
            pass
        self.move_after_id = None
        self.top_hop_active = False
        self.offset_x = 0
        self.offset_y = 0
        self._apply_geometry()
        self._exit_edge_hide_mode()
        self._exit_window_dock_pose()

    def _animate_to_x(self, target_x: int, *, on_complete) -> None:
        self._cancel_move_animation()
        self._exit_edge_hide_mode()
        self._exit_window_dock_pose()
        current_x = self.root.winfo_x()
        if current_x == target_x:
            on_complete()
            return

        direction = 1 if target_x > current_x else -1
        start_base_x = self.base_x
        start_offset_x = self.offset_x
        target_offset_x = target_x - start_base_x
        distance_px = abs(target_x - current_x)
        duration_ms = int(
            self._clamp(
                round(distance_px * MOVE_MS_PER_PIXEL),
                MOVE_MIN_DURATION_MS,
                MOVE_MAX_DURATION_MS,
            )
        )
        start_time = time.monotonic()
        self.top_hop_active = True
        LOGGER.info(
            "Starting top-hop animation: start_base_x=%s current_x=%s target_x=%s target_offset_x=%s direction=%s duration_ms=%s.",
            start_base_x,
            current_x,
            target_x,
            target_offset_x,
            direction,
            duration_ms,
        )
        self.set_state("running-right" if direction > 0 else "running-left")

        def step() -> None:
            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            progress = min(1.0, elapsed_ms / duration_ms)
            next_offset_x = round(
                start_offset_x + (target_offset_x - start_offset_x) * progress
            )
            self._set_motion_offset(next_offset_x)
            current = self.root.winfo_x()
            delta = target_x - current
            LOGGER.info(
                "Top-hop step: base=(%s, %s) offset=(%s, %s) current=(%s, %s) target_x=%s delta=%s progress=%.2f.",
                self.base_x,
                self.base_y,
                self.offset_x,
                self.offset_y,
                current,
                self.root.winfo_y(),
                target_x,
                delta,
                progress,
            )
            if progress >= 1.0 or abs(delta) <= 1:
                self.move_after_id = None
                self.top_hop_active = False
                self.base_x = target_x
                self.offset_x = 0
                self._apply_geometry()
                self.root.update_idletasks()
                LOGGER.info(
                    "Top-hop complete: base=(%s, %s) offset=(%s, %s) actual=(%s, %s).",
                    self.base_x,
                    self.base_y,
                    self.offset_x,
                    self.offset_y,
                    self.root.winfo_x(),
                    self.root.winfo_y(),
                )
                on_complete()
                self.set_state("idle")
                return

            self.move_after_id = self.root.after(MOVE_INTERVAL_MS, step)

        step()

    def _handle_top_dock_click(self) -> bool:
        if self.attached_window is not None and self.attached_window.edge == "top":
            rect = self._get_window_rect(self.attached_window.hwnd)
            if rect is None:
                return False
            left, _top, right, _bottom = rect
            current_slot = self.attached_window.top_slot
            if current_slot is None:
                current_slot, _ = self._nearest_top_slot(self.root.winfo_x(), left, right)
            target_slot, next_pending_slot = self._plan_top_slot_transition(current_slot)
            positions = self._top_slot_positions(left, right)
            self.pending_top_slot = next_pending_slot
            LOGGER.info(
                "Top dock click on attached window: current_slot=%s target_slot=%s next_pending_slot=%s positions=%s current_x=%s.",
                current_slot,
                target_slot,
                next_pending_slot,
                positions,
                self.root.winfo_x(),
            )

            def complete() -> None:
                current_attachment = self.attached_window
                if current_attachment is None:
                    return
                self.attached_window = WindowAttachment(
                    hwnd=current_attachment.hwnd,
                    edge="top",
                    offset=positions[target_slot] - left,
                    top_slot=target_slot,
                )
                self.pending_top_slot = next_pending_slot
                LOGGER.info("Top dock click moved attached pet to slot=%s.", target_slot)

            self._animate_to_x(positions[target_slot], on_complete=complete)
            return True

        if self.screen_edge_attachment == "top":
            work_left, _work_top, work_right, _work_bottom = self._get_work_area()
            current_slot = self.screen_top_slot
            if current_slot is None:
                current_slot, _ = self._nearest_top_slot(self.root.winfo_x(), work_left, work_right)
            target_slot, next_pending_slot = self._plan_top_slot_transition(current_slot)
            positions = self._top_slot_positions(work_left, work_right)
            self.pending_top_slot = next_pending_slot
            LOGGER.info(
                "Top dock click on screen top: current_slot=%s target_slot=%s next_pending_slot=%s positions=%s current_x=%s.",
                current_slot,
                target_slot,
                next_pending_slot,
                positions,
                self.root.winfo_x(),
            )

            def complete() -> None:
                self.screen_edge_attachment = "top"
                self.screen_top_slot = target_slot
                self.pending_top_slot = next_pending_slot
                LOGGER.info("Top dock click moved screen-docked pet to slot=%s.", target_slot)

            self._animate_to_x(positions[target_slot], on_complete=complete)
            return True

        return False

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
        top_origin_x, top_origin_y = self._window_dock_origin("top")
        bottom_origin_x, bottom_origin_y = self._window_dock_origin("bottom")
        left_origin_x, left_origin_y = self._window_dock_origin("left")
        right_origin_x, right_origin_y = self._window_dock_origin("right")
        top_dx, top_dy = self._window_dock_offsets("top")
        bottom_dx, bottom_dy = self._window_dock_offsets("bottom")
        left_dx, left_dy = self._window_dock_offsets("left")
        right_dx, right_dy = self._window_dock_offsets("right")

        left_contact_y = self._clamp(
            current_y + left_origin_y,
            *self._window_dock_contact_y_bounds(rect, left_origin_y),
        )
        right_contact_y = self._clamp(
            current_y + right_origin_y,
            *self._window_dock_contact_y_bounds(rect, right_origin_y),
        )
        top_contact_x = self._clamp(
            current_x + top_origin_x,
            *self._window_dock_contact_x_bounds(rect, top_origin_x),
        )
        bottom_contact_x = self._clamp(
            current_x + bottom_origin_x,
            *self._window_dock_contact_x_bounds(rect, bottom_origin_x),
        )

        positions = [
            (
                "left",
                left - left_origin_x + left_dx,
                left_contact_y - left_origin_y + left_dy,
                left_contact_y - top,
            ),
            (
                "right",
                right - right_origin_x + right_dx,
                right_contact_y - right_origin_y + right_dy,
                right_contact_y - top,
            ),
            (
                "top",
                top_contact_x - top_origin_x + top_dx,
                top - top_origin_y + top_dy,
                top_contact_x - left,
            ),
            (
                "bottom",
                bottom_contact_x - bottom_origin_x + bottom_dx,
                bottom - bottom_origin_y + bottom_dy,
                bottom_contact_x - left,
            ),
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
        origin_x, origin_y = self._window_dock_origin(attachment.edge)
        offset_x, offset_y = self._window_dock_offsets(attachment.edge)

        if attachment.edge in {"left", "right"}:
            lower, upper = self._window_dock_contact_y_bounds(rect, origin_y)
            contact_y = self._clamp(top + attachment.offset, lower, upper)
            y_pos = contact_y - origin_y + offset_y
            x_pos = (left if attachment.edge == "left" else right) - origin_x + offset_x
            return x_pos, y_pos

        if attachment.edge == "top" and attachment.top_slot is not None:
            positions = self._top_slot_positions(left, right)
            slot_index = self._clamp(attachment.top_slot, 0, len(positions) - 1)
            return positions[slot_index] + offset_x, top - origin_y + offset_y

        lower, upper = self._window_dock_contact_x_bounds(rect, origin_x)
        contact_x = self._clamp(left + attachment.offset, lower, upper)
        x_pos = contact_x - origin_x + offset_x
        y_pos = (top if attachment.edge == "top" else bottom) - origin_y + offset_y
        return x_pos, y_pos

    def _set_attachment(self, attachment: WindowAttachment | None) -> None:
        self.attached_window = attachment
        self._clear_screen_attachment()
        self._exit_edge_hide_mode()
        self._exit_window_dock_pose()
        state = "normal" if attachment else "disabled"
        self.menu.entryconfigure("取消窗体吸附", state=state)
        if attachment is None:
            LOGGER.info("Detached from window.")
        else:
            LOGGER.info(
                "Attached to window: hwnd=%s title=%s edge=%s offset=%s top_slot=%s.",
                attachment.hwnd,
                self._get_window_title(attachment.hwnd),
                attachment.edge,
                attachment.offset,
                attachment.top_slot,
            )

    def _configure_window(self) -> None:
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.topmost)
        self.root.configure(bg="white")
        self.root.wm_attributes("-transparentcolor", "white")
        self._apply_geometry()

    def _bind_events(self) -> None:
        self.label.bind("<ButtonPress-1>", self.start_drag)
        self.label.bind("<Button-3>", self.show_context_menu)

    def _position_at_bottom_right(self) -> None:
        left, top, right, bottom = self._get_work_area()
        x_pos = max(left, right - self.frame_width - self.edge_padding)
        y_pos = max(top, bottom - self.frame_height - self.edge_padding)
        self._set_base_position(x_pos, y_pos)
        LOGGER.info("Initial position set to (%s, %s) within work area (%s, %s, %s, %s).", x_pos, y_pos, left, top, right, bottom)

    def show_frame(self, index: int) -> None:
        if self.is_hidden_on_edge or self.is_window_dock_pose:
            return
        frames = self.frames_by_state[self.current_state]
        self.current_index = index % len(frames)
        frame = frames[self.current_index]
        self.label.configure(image=frame.image)
        self.label.image = frame.image
        LOGGER.info("Showing state=%s frame #%s (%s).", self.current_state, self.current_index, Path(frame.path).name)

    def next_frame(self) -> None:
        self.show_frame(self.current_index + 1)

    def set_state(self, state: str) -> None:
        if state not in self.frames_by_state:
            LOGGER.warning("State %s is unavailable; keeping %s.", state, self.current_state)
            return
        self._exit_edge_hide_mode()
        self._exit_window_dock_pose()
        self.current_state = state
        self.current_index = 0
        self.show_frame(0)
        self._schedule_next_frame()
        LOGGER.info("Switched pet state to %s.", self.current_state)

    def cycle_state(self) -> None:
        ordered_states = list(self.frames_by_state)
        next_index = (ordered_states.index(self.current_state) + 1) % len(ordered_states)
        self.set_state(ordered_states[next_index])

    def _schedule_next_frame(self) -> None:
        if self.animation_after_id is not None:
            try:
                self.root.after_cancel(self.animation_after_id)
            except tk.TclError:
                pass
        if self.is_hidden_on_edge and self.edge_hide_edge in self.edge_hide_frames:
            frame = self.edge_hide_frames[self.edge_hide_edge][self.edge_hide_index]
        else:
            frame = self.frames_by_state[self.current_state][self.current_index]
        self.animation_after_id = self.root.after(frame.duration_ms, self._advance_animation)

    def _advance_animation(self) -> None:
        if self.is_hidden_on_edge and self.edge_hide_edge in self.edge_hide_frames:
            frames = self.edge_hide_frames[self.edge_hide_edge]
            self.edge_hide_index = (self.edge_hide_index + 1) % len(frames)
            frame = frames[self.edge_hide_index]
            self.label.configure(image=frame.image)
            self.label.image = frame.image
            LOGGER.info("Showing edge-hide frame edge=%s index=%s (%s).", self.edge_hide_edge, self.edge_hide_index, Path(frame.path).name)
            self._schedule_next_frame()
            return
        self.next_frame()
        self._schedule_next_frame()

    def start_drag(self, event) -> None:
        self._cancel_move_animation()
        self._exit_edge_hide_mode()
        self._exit_window_dock_pose()
        self.root.grab_set()
        self.root.bind("<B1-Motion>", self.on_drag)
        self.root.bind("<ButtonRelease-1>", self.end_drag)
        self.drag_origin_x = event.x_root
        self.drag_origin_y = event.y_root
        self.last_pointer_x = event.x_root
        self.last_pointer_y = event.y_root
        self.window_origin_x = self.root.winfo_x()
        self.window_origin_y = self.root.winfo_y()
        self.is_dragging = False
        self.drag_started_with_window_attachment = self.attached_window is not None
        self.drag_started_with_screen_attachment = self.screen_edge_attachment is not None
        self.drag_restore_state = self.current_state
        self.drag_animation_state = None
        LOGGER.info(
            "Pointer down: pointer=(%s, %s) window_origin=(%s, %s) attached_window=%s screen_edge=%s.",
            self.drag_origin_x,
            self.drag_origin_y,
            self.window_origin_x,
            self.window_origin_y,
            self.attached_window.edge if self.attached_window else None,
            self.screen_edge_attachment,
        )

    def on_drag(self, event) -> None:
        delta_x = event.x_root - self.drag_origin_x
        delta_y = event.y_root - self.drag_origin_y
        self.last_pointer_x = event.x_root
        self.last_pointer_y = event.y_root

        if not self.is_dragging and math.hypot(delta_x, delta_y) > self.drag_threshold:
            self.is_dragging = True
            if self.drag_started_with_window_attachment:
                self.detach_window()
            elif self.drag_started_with_screen_attachment:
                self._clear_screen_attachment()
            LOGGER.info(
                "Drag started: delta=(%s, %s) threshold=%s.",
                delta_x,
                delta_y,
                self.drag_threshold,
            )

        if not self.is_dragging:
            return

        if abs(delta_x) >= max(4, abs(delta_y)):
            direction_state = "running-right" if delta_x > 0 else "running-left"
            if direction_state != self.drag_animation_state:
                self.drag_animation_state = direction_state
                self.set_state(direction_state)
                LOGGER.info("Drag direction animation changed to %s.", direction_state)

        next_x = self.window_origin_x + delta_x
        next_y = self.window_origin_y + delta_y
        self.offset_x = 0
        self.offset_y = 0
        self._set_base_position(next_x, next_y)
        LOGGER.debug("Dragging window to (%s, %s).", next_x, next_y)

    def end_drag(self, event) -> None:
        try:
            self.root.grab_release()
        except tk.TclError:
            pass

        self.root.unbind("<B1-Motion>")
        self.root.unbind("<ButtonRelease-1>")
        self.last_pointer_x = getattr(event, "x_root", self.last_pointer_x)
        self.last_pointer_y = getattr(event, "y_root", self.last_pointer_y)

        if self.is_dragging:
            LOGGER.info("Drag ended at (%s, %s).", self.root.winfo_x(), self.root.winfo_y())
            screen_edge = self._screen_edge_candidate()
            if screen_edge is not None:
                LOGGER.info("Screen edge takes priority on release: edge=%s.", screen_edge)
                self.snap_to_edge()
                self.is_dragging = False
                self.drag_animation_state = None
                return

            attachment = self._find_window_attachment(self.root.winfo_x(), self.root.winfo_y())
            if attachment is not None:
                selected_attachment = attachment[0]
                target_x = attachment[1]
                target_y = attachment[2]
                if selected_attachment.edge == "top":
                    rect = self._get_window_rect(selected_attachment.hwnd)
                    if rect is not None:
                        left, _top, right, _bottom = rect
                        slot_index, target_x = self._nearest_top_slot(self.root.winfo_x(), left, right)
                        selected_attachment = WindowAttachment(
                            hwnd=selected_attachment.hwnd,
                            edge="top",
                            offset=target_x - left,
                            top_slot=slot_index,
                        )
                        target_x, target_y = self._position_for_attachment(selected_attachment, rect)

                self._set_attachment(selected_attachment)
                self.offset_x = 0
                self.offset_y = 0
                self._set_base_position(target_x, target_y)
                self._enter_window_dock_pose(selected_attachment.edge)
                LOGGER.info("Moved to attached window target (%s, %s).", target_x, target_y)
                self.is_dragging = False
                if not self.is_window_dock_pose and self.drag_restore_state in self.frames_by_state:
                    self.set_state(self.drag_restore_state)
                self.drag_animation_state = None
                return

            self.snap_to_edge()
            self.is_dragging = False
            if self.screen_edge_attachment is None and self.drag_restore_state in self.frames_by_state:
                self.set_state(self.drag_restore_state)
            self.drag_animation_state = None
            return

        if self._handle_top_dock_click():
            LOGGER.info("Click detected on top-docked pet, moving between top slots.")
            self.drag_started_with_window_attachment = False
            self.drag_started_with_screen_attachment = False
            return

        LOGGER.info("Click detected, switching to next state.")
        self.drag_started_with_window_attachment = False
        self.drag_started_with_screen_attachment = False
        self.drag_animation_state = None
        self.cycle_state()

    def snap_to_edge(self) -> None:
        left, top, right, bottom = self._get_work_area()

        current_x = self.root.winfo_x()
        current_y = self.root.winfo_y()

        max_x = max(left, right - self.frame_width)
        max_y = max(top, bottom - self.frame_height)

        clamped_x = min(max(current_x, left), max_x)
        clamped_y = min(max(current_y, top), max_y)

        pointer_x = self.last_pointer_x or clamped_x
        pointer_y = self.last_pointer_y or clamped_y

        distances = {
            "left": abs(pointer_x - left),
            "right": abs(right - pointer_x),
            "top": abs(pointer_y - top),
            "bottom": abs(bottom - pointer_y),
        }
        nearest_edge = min(distances, key=distances.get)
        LOGGER.info(
            "Screen edge snap check: position=(%s, %s) pointer=(%s, %s) nearest_edge=%s distance=%s threshold=%s.",
            clamped_x,
            clamped_y,
            pointer_x,
            pointer_y,
            nearest_edge,
            distances[nearest_edge],
            self.snap_threshold,
        )

        if distances[nearest_edge] <= self.snap_threshold:
            if nearest_edge == "left":
                clamped_x = left
                self.screen_edge_attachment = "left"
                self.screen_top_slot = None
                self.pending_top_slot = None
            elif nearest_edge == "right":
                clamped_x = max_x
                self.screen_edge_attachment = "right"
                self.screen_top_slot = None
                self.pending_top_slot = None
            elif nearest_edge == "top":
                clamped_y = top
                slot_index, clamped_x = self._nearest_top_slot(clamped_x, left, right)
                self.screen_edge_attachment = "top"
                self.screen_top_slot = slot_index
                LOGGER.info(
                    "Screen top dock snapped to slot=%s at x=%s (positions=%s).",
                    slot_index,
                    clamped_x,
                    self._top_slot_positions(left, right),
                )
            elif nearest_edge == "bottom":
                clamped_y = max_y
                self.screen_edge_attachment = "bottom"
                self.screen_top_slot = None
                self.pending_top_slot = None
        else:
            self._clear_screen_attachment()
            self._exit_edge_hide_mode()
            self._exit_window_dock_pose()
            LOGGER.info("Screen edge snap skipped because distance %.1f exceeded threshold %s.", distances[nearest_edge], self.snap_threshold)

        self.offset_x = 0
        self.offset_y = 0
        self._set_base_position(clamped_x, clamped_y)
        if self.screen_edge_attachment is not None:
            self._enter_edge_hide_mode(self.screen_edge_attachment)
        LOGGER.info("Screen edge snap result: moved_to=(%s, %s).", clamped_x, clamped_y)

    def toggle_topmost(self) -> None:
        self.topmost = self.topmost_var.get()
        self.root.attributes("-topmost", self.topmost)
        LOGGER.info("Topmost changed: %s.", self.topmost)

    def detach_window(self) -> None:
        self._set_attachment(None)

    def _follow_attached_window(self) -> None:
        try:
            if self.top_hop_active:
                return
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
                        self._set_base_position(next_x, next_y)
                        self._enter_window_dock_pose(self.attached_window.edge)
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
