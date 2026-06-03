from __future__ import annotations

import logging
from pathlib import Path
import tkinter as tk

from image_pipeline import load_pet_frames
from pet_window import PetWindow


TARGET_SIZE = (260, 260)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    configure_logging()
    logger = logging.getLogger("pet.main")
    logger.info("Starting desktop pet application.")
    root = tk.Tk()
    asset_dir = Path(__file__).resolve().parent / "assests"
    logger.info("Using asset directory: %s", asset_dir)
    frames = load_pet_frames(str(asset_dir), TARGET_SIZE)
    PetWindow(root, frames)
    try:
        root.mainloop()
    except Exception:
        logger.exception("Desktop pet crashed.")
        raise
    finally:
        logger.info("Desktop pet application exited.")


if __name__ == "__main__":
    main()
