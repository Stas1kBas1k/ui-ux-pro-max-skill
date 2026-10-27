"""Local data locations. Nothing is stored outside these folders."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("FISCHMACRO_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "FischMacro"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "fischmacro"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def profiles_dir() -> Path:
    return _sub("profiles")


def logs_dir() -> Path:
    return _sub("logs")


def diagnostics_dir() -> Path:
    return _sub("diagnostics")


def templates_dir() -> Path:
    return _sub("templates")


def settings_file() -> Path:
    return data_dir() / "settings.json"


def stats_db() -> Path:
    return data_dir() / "statistics.sqlite3"


def resource_path(*parts: str) -> Path:
    """Path to a bundled resource, working both from source and from a PyInstaller build."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root.joinpath(*parts)
