"""Local data locations. Nothing is stored outside these folders."""
from __future__ import annotations

import os
import sys
from pathlib import Path


NOTE: list[str] = []  # why the data folder is where it is (shown in the log and the diagnostics zip)


def _writable(base: Path) -> bool:
    try:
        base.mkdir(parents=True, exist_ok=True)
        probe = base / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError as exc:
        NOTE.append(f"cannot write to {base}: {exc}")
        return False


def _portable_dir() -> Path | None:
    """The packaged app is portable: its data lives in a 'data' folder next to FischMacro.exe, so everything
    stays on the drive you unzipped it to (e.g. D:\\MACROS) and nothing is written to drive C. If that folder
    cannot be written (a protected folder, antivirus), other folders on the same drive are tried first."""
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).resolve().parent
    candidates = [exe_dir / "data", exe_dir.parent / "FischMacro-data", Path(exe_dir.anchor) / "FischMacro-data"]
    for base in dict.fromkeys(candidates):  # same order, no repeats
        if _writable(base):
            return base
    return None


_CHOSEN: Path | None = None


def data_dir() -> Path:
    global _CHOSEN
    override = os.environ.get("FISCHMACRO_HOME")
    if override:
        base = Path(override)
    elif _CHOSEN is not None:
        base = _CHOSEN
    elif (portable := _portable_dir()) is not None:
        base = _CHOSEN = portable
        _move_old_user_folder(base)
    elif sys.platform == "win32":
        base = _CHOSEN = _user_folder()
        NOTE.append("no writable folder on the app's drive: using the Windows user folder")
    else:
        base = _CHOSEN = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "fischmacro"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _user_folder() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "FischMacro"


def _move_old_user_folder(base: Path) -> None:
    """Older versions (or a run where the app's folder could not be written) kept everything in
    %APPDATA%\\FischMacro on drive C. Bring it over to the portable folder - profiles, settings, statistics and
    logs the new folder does not have yet - and then remove it from drive C."""
    if sys.platform != "win32":
        return
    old = _user_folder()
    try:
        if not old.is_dir() or old.resolve() == base.resolve():
            return
        import shutil
        for item in old.rglob("*"):
            target = base / item.relative_to(old)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif not target.exists():  # never overwrite what the portable folder already has
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        shutil.rmtree(old)
        NOTE.append(f"moved the old data from {old} to {base}")
    except OSError as exc:
        NOTE.append(f"could not move the old data from {old}: {exc}")


def describe_location() -> str:
    """One line for the log: where data is kept, and why if it is not next to the app."""
    text = f"Data folder: {data_dir()}"
    return text + (" (" + "; ".join(NOTE) + ")" if NOTE else "")


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
