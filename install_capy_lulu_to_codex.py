from __future__ import annotations

import json
import shutil
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    source_dir = root / "artifacts" / "hatch-pet"
    pet_json = source_dir / "pet.json"
    spritesheet = source_dir / "spritesheet.webp"

    if not pet_json.is_file() or not spritesheet.is_file():
        raise FileNotFoundError("Missing final pet package files under artifacts/hatch-pet.")

    manifest = json.loads(pet_json.read_text(encoding="utf-8"))
    pet_id = manifest["id"]

    codex_home = Path.home() / ".codex"
    target_dir = codex_home / "pets" / pet_id
    target_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(pet_json, target_dir / "pet.json")
    shutil.copy2(spritesheet, target_dir / "spritesheet.webp")

    print(f"installed {pet_id} to {target_dir}")


if __name__ == "__main__":
    main()
