from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent
CELL = 64
SOURCE_CELL_WIDTH = 192
SOURCE_CELL_HEIGHT = 208
ATLAS_COLUMNS = 8
ATLAS_ROWS = 9
PADDING = 2

SOURCE_ATLAS = ROOT / "artifacts" / "hatch-pet" / "spritesheet.png"
GODOT_ATLAS = ROOT / "godot_pet" / "assets" / "hatch-pet" / "spritesheet-64.png"
GODOT_BASE_ATLAS = ROOT / "godot_pet" / "assets" / "hatch-pet" / "spritesheet-64-base.png"
GODOT_EDGE_DIR = ROOT / "godot_pet" / "assets" / "edge-hide-64"
GODOT_DOCK_DIR = ROOT / "godot_pet" / "assets" / "window-dock-64"
SOURCE_EDGE_DIR = ROOT / "artifacts" / "edge-hide"
SOURCE_DOCK_DIR = ROOT / "artifacts" / "window-dock"


EDGE_FILES = [
    "bottom-edge-blink-clean.png",
    "bottom-edge-clean.png",
    "left-edge-blink-clean.png",
    "left-edge-clean.png",
    "right-edge-blink-clean.png",
    "right-edge-clean.png",
    "top-edge-blink-clean.png",
    "top-edge-clean.png",
]

DOCK_FILES = [
    "bottom-blink-clean.png",
    "bottom-clean.png",
    "left-blink-clean.png",
    "left-clean.png",
    "right-blink-clean.png",
    "right-clean.png",
    "top-blink-clean.png",
    "top-clean.png",
    "top-v2-clean.png",
]


def fit_to_cell(image: Image.Image, padding: int = PADDING) -> Image.Image:
    image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    output = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
    if bbox is None:
        return output
    subject = image.crop(bbox)
    max_size = CELL - padding * 2
    scale = min(max_size / subject.width, max_size / subject.height)
    size = (max(1, round(subject.width * scale)), max(1, round(subject.height * scale)))
    subject = subject.resize(size, Image.Resampling.LANCZOS)
    x_pos = (CELL - subject.width) // 2
    y_pos = (CELL - subject.height) // 2
    output.alpha_composite(subject, (x_pos, y_pos))
    return output


def sanitize_alpha(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha == 0:
                pixels[x, y] = (0, 0, 0, 0)
    return image


def build_atlas() -> None:
    source = Image.open(SOURCE_ATLAS).convert("RGBA")
    output = Image.new("RGBA", (CELL * ATLAS_COLUMNS, CELL * ATLAS_ROWS), (0, 0, 0, 0))
    for row in range(ATLAS_ROWS):
        for column in range(ATLAS_COLUMNS):
            box = (
                column * SOURCE_CELL_WIDTH,
                row * SOURCE_CELL_HEIGHT,
                (column + 1) * SOURCE_CELL_WIDTH,
                (row + 1) * SOURCE_CELL_HEIGHT,
            )
            cell = fit_to_cell(source.crop(box))
            output.alpha_composite(cell, (column * CELL, row * CELL))
    GODOT_ATLAS.parent.mkdir(parents=True, exist_ok=True)
    output = sanitize_alpha(output)
    output.save(GODOT_ATLAS)
    output.save(GODOT_BASE_ATLAS)


def build_flat_assets(source_dir: Path, output_dir: Path, filenames: list[str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        source_path = source_dir / filename
        if not source_path.exists():
            continue
        output_path = output_dir / filename
        fit_to_cell(Image.open(source_path)).save(output_path)


def main() -> None:
    build_atlas()
    build_flat_assets(SOURCE_EDGE_DIR, GODOT_EDGE_DIR, EDGE_FILES)
    build_flat_assets(SOURCE_DOCK_DIR, GODOT_DOCK_DIR, DOCK_FILES)
    print(f"wrote {GODOT_ATLAS}")
    print(f"wrote {GODOT_EDGE_DIR}")
    print(f"wrote {GODOT_DOCK_DIR}")


if __name__ == "__main__":
    main()
