from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "MB-CF-Optimizer"


def resource_path(name: str) -> Path:
    return Path(__file__).resolve().parent / "resources" / name


def app_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path
