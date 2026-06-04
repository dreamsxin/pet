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
EdgeHideFrames = dict[str, list[PetFrame]]


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


def load_edge_hide_frames(asset_dir: str, target_size: tuple[int, int]) -> EdgeHideFrames:
    asset_path = Path(asset_dir)
    mapping = {
        "top": [asset_path / "bottom-edge-clean.png", asset_path / "bottom-edge-blink-clean.png"],
        "bottom": [asset_path / "top-edge-clean.png", asset_path / "top-edge-blink-clean.png"],
        "left": [asset_path / "left-edge-clean.png", asset_path / "left-edge-blink-clean.png"],
        "right": [asset_path / "right-edge-clean.png", asset_path / "right-edge-blink-clean.png"],
    }
    loaded: EdgeHideFrames = {}
    durations = [1400, 140, 1400]
    for edge, paths in mapping.items():
        if not all(path.is_file() for path in paths):
            missing = [str(path) for path in paths if not path.is_file()]
            LOGGER.warning("Missing edge-hide image(s) for %s: %s", edge, missing)
            continue
        open_image = Image.open(paths[0]).convert("RGBA")
        blink_image = Image.open(paths[1]).convert("RGBA")
        prepared_open = prepare_edge_hide_frame(open_image, edge, target_size)
        prepared_blink = prepare_edge_hide_frame(blink_image, edge, target_size)
        rendered_open = ImageTk.PhotoImage(prepared_open)
        rendered_blink = ImageTk.PhotoImage(prepared_blink)
        loaded[edge] = [
            PetFrame(
                path=str(paths[0]),
                image=rendered_open,
                width=rendered_open.width(),
                height=rendered_open.height(),
                duration_ms=durations[0],
            ),
            PetFrame(
                path=str(paths[1]),
                image=rendered_blink,
                width=rendered_blink.width(),
                height=rendered_blink.height(),
                duration_ms=durations[1],
            ),
            PetFrame(
                path=str(paths[0]),
                image=rendered_open,
                width=rendered_open.width(),
                height=rendered_open.height(),
                duration_ms=durations[2],
            ),
        ]
        LOGGER.info("Loaded edge-hide animation for %s from %s and %s.", edge, paths[0], paths[1])
    return loaded


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


def prepare_edge_hide_frame(
    source: Image.Image,
    edge: str,
    target_size: tuple[int, int],
) -> Image.Image:
    bbox = source.getbbox()
    if bbox is None:
        return Image.new("RGBA", target_size, (0, 0, 0, 0))

    sprite = source.crop(bbox)
    viewport = Image.new("RGBA", target_size, (0, 0, 0, 0))

    crop = sprite.copy()
    crop.thumbnail(target_size, Image.Resampling.LANCZOS)

    if edge == "left":
        x_pos = 0
        y_pos = max(0, (target_size[1] - crop.height) // 2)
    elif edge == "right":
        x_pos = max(0, target_size[0] - crop.width)
        y_pos = max(0, (target_size[1] - crop.height) // 2)
    elif edge == "top":
        x_pos = max(0, (target_size[0] - crop.width) // 2)
        y_pos = 0
    else:
        x_pos = max(0, (target_size[0] - crop.width) // 2)
        y_pos = max(0, target_size[1] - crop.height)

    viewport.alpha_composite(crop, (x_pos, y_pos))
    return viewport
