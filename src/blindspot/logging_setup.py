from __future__ import annotations

import logging
from pathlib import Path

LOG_LEVELS = {
    "Off": logging.CRITICAL + 1,
    "Debug": logging.DEBUG,
    "Information": logging.INFO,
    "Warnings": logging.WARNING,
    "Errors": logging.ERROR,
}


def configure_logging(path: Path, level: str = "Off") -> None:
    logging.disable(logging.NOTSET)
    if level == "Off":
        logging.basicConfig(
            level=logging.CRITICAL + 1,
            handlers=[logging.NullHandler()],
            force=True,
        )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=LOG_LEVELS.get(level, logging.CRITICAL + 1),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(path, encoding="utf-8"),
        ],
        force=True,
    )
    logging.getLogger("blindspot").info("BlindSpot logging started")
