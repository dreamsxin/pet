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
    package_dir = Path(__file__).resolve().parent / "artifacts" / "hatch-pet"
    logger.info("Using pet package directory: %s", package_dir)
    frames_by_state = load_pet_frames(str(package_dir), TARGET_SIZE)
    window = PetWindow(root, frames_by_state)
    root.bind("1", lambda _event: window.set_state("idle"))
    root.bind("2", lambda _event: window.set_state("running-right"))
    root.bind("3", lambda _event: window.set_state("running-left"))
    root.bind("4", lambda _event: window.set_state("waving"))
    root.bind("5", lambda _event: window.set_state("jumping"))
    root.bind("6", lambda _event: window.set_state("failed"))
    root.bind("7", lambda _event: window.set_state("waiting"))
    root.bind("8", lambda _event: window.set_state("running"))
    root.bind("9", lambda _event: window.set_state("review"))
    try:
        root.mainloop()
    except Exception:
        logger.exception("Desktop pet crashed.")
        raise
    finally:
        logger.info("Desktop pet application exited.")


if __name__ == "__main__":
    main()
