from __future__ import annotations

from pathlib import Path

from PIL import Image


CELL_WIDTH = 192
CELL_HEIGHT = 208

ROWS_TO_REBUILD = {
    "running-right": 1,
    "running-left": 2,
    "waving": 3,
    "jumping": 4,
    "running": 7,
}

ROW_FRAME_COUNTS = {
    "running-right": 8,
    "running-left": 8,
    "waving": 4,
    "jumping": 5,
    "running": 6,
}


def clear_transparent_rgb(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    data = bytearray(rgba.tobytes())
    for index in range(0, len(data), 4):
        if data[index + 3] == 0:
            data[index] = 0
            data[index + 1] = 0
            data[index + 2] = 0
    return Image.frombytes("RGBA", rgba.size, bytes(data))


def main() -> None:
    root = Path(__file__).resolve().parent
    workbench = root / "artifacts" / "workbench"
    final_dir = root / "artifacts" / "hatch-pet"

    base_atlas_path = workbench / "base-spritesheet.png"
    final_png = final_dir / "spritesheet.png"
    final_webp = final_dir / "spritesheet.webp"

    base_atlas = Image.open(base_atlas_path).convert("RGBA")

    frames_root = workbench / "rebuild-frames" / "frames"
    if not frames_root.is_dir():
        raise FileNotFoundError(
            "Missing rebuild-frames/frames. Generate fresh row strips before rebuilding the atlas."
        )

    for state, row_index in ROWS_TO_REBUILD.items():
        frame_count = ROW_FRAME_COUNTS[state]
        row_top = row_index * CELL_HEIGHT
        row_bottom = row_top + CELL_HEIGHT
        # Clear the whole target row before pasting new frames so no old opaque
        # pixels survive behind transparent regions of the regenerated frames.
        for y_pos in range(row_top, row_bottom):
            for x_pos in range(0, CELL_WIDTH * 8):
                base_atlas.putpixel((x_pos, y_pos), (0, 0, 0, 0))
        for column_index in range(frame_count):
            frame_path = frames_root / state / f"{column_index:02d}.png"
            frame = Image.open(frame_path).convert("RGBA")
            x_pos = column_index * CELL_WIDTH
            y_pos = row_index * CELL_HEIGHT
            base_atlas.paste(frame, (x_pos, y_pos), frame)

    rebuilt = clear_transparent_rgb(base_atlas)
    rebuilt.save(final_png)
    rebuilt.save(final_webp, format="WEBP", lossless=True, quality=100, method=6, exact=True)

    print(f"wrote {final_png}")
    print(f"wrote {final_webp}")


if __name__ == "__main__":
    main()
