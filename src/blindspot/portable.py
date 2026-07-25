from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        if (
            sys.platform == "darwin"
            and executable.parent.name == "MacOS"
            and executable.parent.parent.name == "Contents"
        ):
            return executable.parents[3]
        return executable.parent
    return Path(__file__).resolve().parents[2]


def resource_directory() -> Path:
    if getattr(sys, "frozen", False):
        bundled = getattr(sys, "_MEIPASS", "")
        if bundled:
            return Path(bundled).resolve()
    return application_directory()


class PortableStore:
    def __init__(self, root: Path | None = None) -> None:
        if root is not None:
            self.root = root
            self.root.mkdir(parents=True, exist_ok=True)
        else:
            preferred = application_directory() / "data"
            try:
                preferred.mkdir(parents=True, exist_ok=True)
                self.root = preferred
            except OSError:
                if sys.platform != "darwin":
                    raise
                self.root = (
                    Path.home()
                    / "Library"
                    / "Application Support"
                    / "BlindSpot"
                )
                self.root.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()

    def read(self, name: str, default: Any = None) -> Any:
        path = self.root / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def write(self, name: str, value: Any) -> None:
        with self._write_lock:
            path = self.root / name
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(value, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(path)

    def remove(self, name: str) -> None:
        with self._write_lock:
            path = self.root / name
            if path.exists():
                path.unlink()
