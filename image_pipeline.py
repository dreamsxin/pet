from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import tkinter as tk

from PIL import Image, ImageTk


LOGGER = logging.getLogger("pet.image")

CELL_WIDTH = 192
CELL_HEIGHT = 208
ATLAS_COLUMNS = 8
ROW_SPECS = {
    "idle": (0, 6),
    "running-right": (1, 8),
    "running-left": (2, 8),
    "waving": (3, 4),
    "jumping": (4, 5),
    "failed": (5, 8),
    "waiting": (6, 6),
    "running": (7, 6),
    "review": (8, 6),
}
ROW_DURATIONS = {
    "idle": [280, 110, 110, 140, 140, 320],
    "running-right": [120, 120, 120, 120, 120, 120, 120, 220],
    "running-left": [120, 120, 120, 120, 120, 120, 120, 220],
    "waving": [140, 140, 140, 280],
    "jumping": [140, 140, 140, 140, 280],
    "failed": [140, 140, 140, 140, 140, 140, 140, 240],
    "waiting": [150, 150, 150, 150, 150, 260],
    "running": [120, 120, 120, 120, 120, 220],
    "review": [150, 150, 150, 150, 150, 280],
}


@dataclass(slots=True)
class PetFrame:
    path: str
    image: ImageTk.PhotoImage
    width: int
    height: int
    duration_ms: int


AtlasFrames = dict[str, list[PetFrame]]


def load_pet_frames(asset_dir: str, target_size: tuple[int, int]) -> AtlasFrames:
    asset_path = Path(asset_dir)
    manifest_path = asset_path / "pet.json"
    if manifest_path.is_file():
        return load_pet_frames_from_package(asset_path, target_size)
    return load_pet_frames_from_directory(asset_path, target_size)


def load_pet_frames_from_package(package_dir: Path, target_size: tuple[int, int]) -> AtlasFrames:
    atlas_path = package_dir / "spritesheet.webp"
    if not atlas_path.is_file():
        raise FileNotFoundError(f"Missing spritesheet.webp in {package_dir}")

    LOGGER.info("Loading atlas package from %s with target size %s.", atlas_path, target_size)
    with Image.open(atlas_path) as atlas_image:
        atlas = atlas_image.convert("RGBA")

    frames_by_state: AtlasFrames = {}
    for state, (row_index, frame_count) in ROW_SPECS.items():
        durations = ROW_DURATIONS[state]
        state_frames: list[PetFrame] = []
        for column_index in range(frame_count):
            left = column_index * CELL_WIDTH
            top = row_index * CELL_HEIGHT
            cell = atlas.crop((left, top, left + CELL_WIDTH, top + CELL_HEIGHT))
            rendered = render_frame(cell, target_size)
            state_frames.append(
                PetFrame(
                    path=f"{atlas_path}#{state}:{column_index}",
                    image=rendered,
                    width=rendered.width(),
                    height=rendered.height(),
                    duration_ms=durations[column_index],
                )
            )
        frames_by_state[state] = state_frames
        LOGGER.info("Loaded %s atlas frame(s) for state %s.", len(state_frames), state)
    return frames_by_state


def load_pet_frames_from_directory(asset_dir: Path, target_size: tuple[int, int]) -> AtlasFrames:
    frame_paths = sorted(asset_dir.glob("*.jpg"))
    if not frame_paths:
        raise FileNotFoundError(f"No JPG files found in {asset_dir}")

    LOGGER.info("Loading %s loose frame(s) from %s with target size %s.", len(frame_paths), asset_dir, target_size)
    idle_frames = [prepare_transparent_frame(path, target_size) for path in frame_paths]
    return {"idle": idle_frames}


def prepare_transparent_frame(path: Path, target_size: tuple[int, int]) -> PetFrame:
    source = Image.open(path).convert("RGBA")
    source.thumbnail(target_size, Image.Resampling.LANCZOS)
    rendered = ImageTk.PhotoImage(source)
    width, height = rendered.width(), rendered.height()
    LOGGER.info("Prepared loose frame %s rendered=%sx%s.", path.name, width, height)
    return PetFrame(path=str(path), image=rendered, width=width, height=height, duration_ms=180)


def render_frame(source: Image.Image, target_size: tuple[int, int]) -> ImageTk.PhotoImage:
    frame = source.copy()
    frame.thumbnail(target_size, Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(frame)
