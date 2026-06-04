from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


CELL_WIDTH = 192
CELL_HEIGHT = 208
ATLAS_COLUMNS = 8
ATLAS_ROWS = 9
CHROMA = (255, 0, 255)


ROW_SPECS = {
    "running-right": {"row": 1, "count": 8},
    "running-left": {"row": 2, "count": 8},
    "waiting": {"row": 6, "count": 6},
}


def remove_chroma(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                pixels[x, y] = (0, 0, 0, 0)
                continue
            if abs(red - CHROMA[0]) <= 36 and abs(green - CHROMA[1]) <= 36 and abs(blue - CHROMA[2]) <= 36:
                pixels[x, y] = (0, 0, 0, 0)
    return image


def normalize_cell(frame: Image.Image) -> Image.Image:
    frame = remove_chroma(frame)
    bbox = frame.getchannel("A").getbbox()
    cell = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    if bbox is None:
        return cell
    subject = frame.crop(bbox)
    max_w = CELL_WIDTH - 18
    max_h = CELL_HEIGHT - 18
    scale = min(max_w / subject.width, max_h / subject.height, 1.0)
    new_size = (max(1, round(subject.width * scale)), max(1, round(subject.height * scale)))
    subject = subject.resize(new_size, Image.Resampling.LANCZOS)
    x_pos = (CELL_WIDTH - subject.width) // 2
    y_pos = CELL_HEIGHT - subject.height - 8
    cell.alpha_composite(subject, (x_pos, y_pos))
    return cell


def split_strip(strip_path: Path, frame_count: int) -> list[Image.Image]:
    strip = Image.open(strip_path).convert("RGBA")
    slot_width = strip.width / frame_count
    frames: list[Image.Image] = []
    for index in range(frame_count):
        left = round(index * slot_width)
        right = round((index + 1) * slot_width)
        raw = strip.crop((left, 0, right, strip.height))
        frames.append(normalize_cell(raw))
    return frames


def clear_row(atlas: Image.Image, row: int) -> None:
    transparent = Image.new("RGBA", (CELL_WIDTH * ATLAS_COLUMNS, CELL_HEIGHT), (0, 0, 0, 0))
    atlas.alpha_composite(transparent, (0, row * CELL_HEIGHT))
    draw_region = Image.new("RGBA", atlas.size, (0, 0, 0, 0))
    atlas.paste(draw_region.crop((0, row * CELL_HEIGHT, CELL_WIDTH * ATLAS_COLUMNS, (row + 1) * CELL_HEIGHT)), (0, row * CELL_HEIGHT))


def sanitize_transparent_rgb(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                pixels[x, y] = (0, 0, 0, 0)
    return image


def replace_rows(atlas_path: Path, strips: dict[str, Path], output_path: Path) -> None:
    atlas = Image.open(atlas_path).convert("RGBA")
    expected_size = (CELL_WIDTH * ATLAS_COLUMNS, CELL_HEIGHT * ATLAS_ROWS)
    if atlas.size != expected_size:
        raise ValueError(f"Unexpected atlas size {atlas.size}; expected {expected_size}")

    for state, strip_path in strips.items():
        spec = ROW_SPECS[state]
        row = spec["row"]
        clear = Image.new("RGBA", (CELL_WIDTH * ATLAS_COLUMNS, CELL_HEIGHT), (0, 0, 0, 0))
        atlas.paste(clear, (0, row * CELL_HEIGHT))
        frames = split_strip(strip_path, spec["count"])
        for column, frame in enumerate(frames):
            atlas.alpha_composite(frame, (column * CELL_WIDTH, row * CELL_HEIGHT))

    atlas = sanitize_transparent_rgb(atlas)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--atlas", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--running-right", required=True, type=Path)
    parser.add_argument("--running-left", required=True, type=Path)
    parser.add_argument("--waiting", required=True, type=Path)
    args = parser.parse_args()
    replace_rows(
        args.atlas,
        {
            "running-right": args.running_right,
            "running-left": args.running_left,
            "waiting": args.waiting,
        },
        args.output,
    )


if __name__ == "__main__":
    main()
