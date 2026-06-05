from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


CELL = 64
ATLAS_COLUMNS = 8
ATLAS_ROWS = 9
CHROMA = (255, 0, 255)

ROW_SPECS = {
    "idle": {"row": 0, "count": 6},
    "running-right": {"row": 1, "count": 8},
    "running-left": {"row": 2, "count": 8},
    "waving": {"row": 3, "count": 4},
    "jumping": {"row": 4, "count": 5},
    "failed": {"row": 5, "count": 8},
    "waiting": {"row": 6, "count": 6},
    "running": {"row": 7, "count": 6},
    "review": {"row": 8, "count": 6},
}


def remove_chroma(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                pixels[x, y] = (0, 0, 0, 0)
            elif abs(red - CHROMA[0]) <= 42 and abs(green - CHROMA[1]) <= 42 and abs(blue - CHROMA[2]) <= 42:
                pixels[x, y] = (0, 0, 0, 0)
    return image


def fit_slot(slot: Image.Image) -> Image.Image:
    slot = remove_chroma(slot)
    bbox = slot.getchannel("A").getbbox()
    output = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
    if bbox is None:
        return output
    subject = slot.crop(bbox)
    scale = min(58 / subject.width, 58 / subject.height, 1.0)
    size = (max(1, round(subject.width * scale)), max(1, round(subject.height * scale)))
    subject = subject.resize(size, Image.Resampling.LANCZOS)
    output.alpha_composite(subject, ((CELL - size[0]) // 2, (CELL - size[1]) // 2))
    return output


def split_strip(strip_path: Path, count: int) -> list[Image.Image]:
    strip = Image.open(strip_path).convert("RGBA")
    slot_width = strip.width / count
    frames: list[Image.Image] = []
    for index in range(count):
        left = round(index * slot_width)
        right = round((index + 1) * slot_width)
        frames.append(fit_slot(strip.crop((left, 0, right, strip.height))))
    return frames


def sanitize_alpha(image: Image.Image) -> Image.Image:
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                pixels[x, y] = (0, 0, 0, 0)
    return image


def build(strips_dir: Path, output: Path, base_atlas: Path | None = None, allow_partial: bool = False) -> None:
    if base_atlas is not None:
        atlas = Image.open(base_atlas).convert("RGBA")
        expected = (CELL * ATLAS_COLUMNS, CELL * ATLAS_ROWS)
        if atlas.size != expected:
            raise ValueError(f"Unexpected base atlas size {atlas.size}; expected {expected}")
    else:
        atlas = Image.new("RGBA", (CELL * ATLAS_COLUMNS, CELL * ATLAS_ROWS), (0, 0, 0, 0))
    missing: list[str] = []
    for state, spec in ROW_SPECS.items():
        strip_path = strips_dir / f"{state}.png"
        if not strip_path.exists():
            missing.append(state)
            continue
        frames = split_strip(strip_path, spec["count"])
        clear = Image.new("RGBA", (CELL * ATLAS_COLUMNS, CELL), (0, 0, 0, 0))
        atlas.paste(clear, (0, spec["row"] * CELL))
        for column, frame in enumerate(frames):
            atlas.alpha_composite(frame, (column * CELL, spec["row"] * CELL))
    if missing and not allow_partial:
        raise FileNotFoundError(f"Missing row strips: {', '.join(missing)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    sanitize_alpha(atlas).save(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strips-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-atlas", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    build(args.strips_dir, args.output, args.base_atlas, args.allow_partial)


if __name__ == "__main__":
    main()
