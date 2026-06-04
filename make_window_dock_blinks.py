from __future__ import annotations

from collections import deque
from pathlib import Path
from statistics import median

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "artifacts" / "window-dock"
GODOT_DIR = ROOT / "godot_pet" / "assets" / "window-dock"
FILES = ["top-clean.png", "bottom-clean.png", "left-clean.png", "right-clean.png"]


def connected_components(points: set[tuple[int, int]]) -> list[tuple[int, tuple[int, int, int, int]]]:
    seen: set[tuple[int, int]] = set()
    components: list[tuple[int, tuple[int, int, int, int]]] = []
    for start in list(points):
        if start in seen:
            continue
        queue = deque([start])
        seen.add(start)
        xs: list[int] = []
        ys: list[int] = []
        while queue:
            x, y = queue.popleft()
            xs.append(x)
            ys.append(y)
            for nx in range(x - 1, x + 2):
                for ny in range(y - 1, y + 2):
                    if (nx, ny) in points and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        queue.append((nx, ny))
        components.append((len(xs), (min(xs), min(ys), max(xs), max(ys))))
    return components


def find_eye_boxes(image: Image.Image) -> list[tuple[int, int, int, int]]:
    pixels = image.load()
    alpha_bbox = image.getchannel("A").getbbox()
    if alpha_bbox is None:
        return []
    left, top, right, bottom = alpha_bbox
    max_y = top + int((bottom - top) * 0.55)
    white_points: set[tuple[int, int]] = set()
    for y in range(top, max_y):
        for x in range(left, right):
            red, green, blue, alpha = pixels[x, y]
            if alpha > 120 and red > 210 and green > 210 and blue > 210:
                white_points.add((x, y))

    candidates: list[tuple[int, tuple[int, int, int, int]]] = []
    for area, box in connected_components(white_points):
        x1, y1, x2, y2 = box
        width = x2 - x1 + 1
        height = y2 - y1 + 1
        if area < 45 or area > 450:
            continue
        if width < 8 or height < 8 or width > 42 or height > 42:
            continue
        if width / height < 0.45 or width / height > 2.2:
            continue
        candidates.append((area, box))

    pairs: list[tuple[float, tuple[int, int, int, int], tuple[int, int, int, int]]] = []
    for index, (_area_a, box_a) in enumerate(candidates):
        for _area_b, box_b in candidates[index + 1 :]:
            center_a_x = (box_a[0] + box_a[2]) / 2
            center_a_y = (box_a[1] + box_a[3]) / 2
            center_b_x = (box_b[0] + box_b[2]) / 2
            center_b_y = (box_b[1] + box_b[3]) / 2
            x_gap = abs(center_a_x - center_b_x)
            y_gap = abs(center_a_y - center_b_y)
            if x_gap < 45:
                continue
            # A true pair of eyes usually sits on almost the same face latitude.
            score = y_gap * 8 - x_gap * 0.15
            pairs.append((score, box_a, box_b))
    if pairs:
        pairs.sort(key=lambda item: item[0])
        return sorted([pairs[0][1], pairs[0][2]], key=lambda box: box[0])
    candidates.sort(key=lambda item: (-item[0], item[1][1]))
    return sorted([item[1] for item in candidates[:2]], key=lambda box: box[0])


def sample_skin_color(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    pixels = image.load()
    width, height = image.size
    x1, y1, x2, y2 = box
    samples: list[tuple[int, int, int]] = []
    for y in range(max(0, y1 - 8), min(height, y2 + 9)):
        for x in range(max(0, x1 - 8), min(width, x2 + 9)):
            if x1 - 2 <= x <= x2 + 2 and y1 - 2 <= y <= y2 + 2:
                continue
            red, green, blue, alpha = pixels[x, y]
            if alpha < 180:
                continue
            if red > 210 and green > 210 and blue > 210:
                continue
            if red > 190 and green > 120 and blue < 90:
                samples.append((red, green, blue))
    if not samples:
        return (247, 188, 45, 255)
    return (
        int(median([color[0] for color in samples])),
        int(median([color[1] for color in samples])),
        int(median([color[2] for color in samples])),
        255,
    )


def draw_closed_eye(image: Image.Image, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    pad_x = max(8, int((x2 - x1 + 1) * 0.55))
    pad_y = max(8, int((y2 - y1 + 1) * 0.45))
    cover = (x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y)
    draw = ImageDraw.Draw(image)
    draw.ellipse(cover, fill=sample_skin_color(image, box))

    scale = 4
    overlay = Image.new("RGBA", (image.width * scale, image.height * scale), (0, 0, 0, 0))
    high = ImageDraw.Draw(overlay)
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2 + 1
    half = (x2 - x1 + 1) * 0.42
    high.arc(
        (
            int((cx - half) * scale),
            int((cy - 4) * scale),
            int((cx + half) * scale),
            int((cy + 8) * scale),
        ),
        start=12,
        end=168,
        fill=(48, 35, 22, 255),
        width=max(2, int(2.1 * scale)),
    )
    overlay = overlay.resize(image.size, Image.Resampling.LANCZOS)
    image.alpha_composite(overlay)


def make_blink(source_path: Path, output_path: Path) -> None:
    image = Image.open(source_path).convert("RGBA")
    boxes = find_eye_boxes(image)
    if len(boxes) < 2:
        raise RuntimeError(f"Could not find two eyes in {source_path}")
    for box in boxes[:2]:
        draw_closed_eye(image, box)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def main() -> None:
    for filename in FILES:
        source = SOURCE_DIR / filename
        output = SOURCE_DIR / filename.replace("-clean.png", "-blink-clean.png")
        make_blink(source, output)
        godot_output = GODOT_DIR / output.name
        godot_output.parent.mkdir(parents=True, exist_ok=True)
        Image.open(output).save(godot_output)
        print(f"generated {output} and {godot_output}")


if __name__ == "__main__":
    main()
