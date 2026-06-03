from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import tkinter as tk

from PIL import Image, ImageTk


WHITE_CUTOFF = 245
SOFT_EDGE_CUTOFF = 230
LOGGER = logging.getLogger("pet.image")


@dataclass(slots=True)
class PetFrame:
    path: str
    image: ImageTk.PhotoImage
    width: int
    height: int


def load_pet_frames(asset_dir: str, target_size: tuple[int, int]) -> list[PetFrame]:
    asset_path = Path(asset_dir)
    frame_paths = sorted(asset_path.glob("*.JPG"))
    if not frame_paths:
        raise FileNotFoundError(f"No JPG files found in {asset_path}")

    LOGGER.info("Loading %s frame(s) from %s with target size %s.", len(frame_paths), asset_path, target_size)
    return [prepare_transparent_frame(str(frame_path), target_size) for frame_path in frame_paths]


def prepare_transparent_frame(path: str, target_size: tuple[int, int]) -> PetFrame:
    source = Image.open(path).convert("RGBA")
    original_size = source.size
    source.thumbnail(target_size, Image.Resampling.LANCZOS)

    rgba_pixels = []
    for red, green, blue, alpha in source.getdata():
        minimum = min(red, green, blue)
        maximum = max(red, green, blue)

        if minimum >= WHITE_CUTOFF:
            rgba_pixels.append((red, green, blue, 0))
            continue

        if minimum >= SOFT_EDGE_CUTOFF and maximum - minimum <= 18:
            distance = WHITE_CUTOFF - minimum
            softened_alpha = max(0, min(255, distance * 18))
            rgba_pixels.append((red, green, blue, softened_alpha))
            continue

        rgba_pixels.append((red, green, blue, alpha))

    source.putdata(rgba_pixels)
    rendered = ImageTk.PhotoImage(source)
    width, height = rendered.width(), rendered.height()
    LOGGER.info("Prepared frame %s: original=%s rendered=%sx%s.", Path(path).name, original_size, width, height)
    return PetFrame(path=path, image=rendered, width=width, height=height)
