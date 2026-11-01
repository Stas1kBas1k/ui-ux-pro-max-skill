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
    if _writable(exe_dir / "data"):
        return exe_dir / "data"
    # The app's own folder is blocked (player's log: the app was in Music on drive C, which Windows' ransomware
    # protection guards, reported as "WinError 2"). When the app is on the system drive, another fixed drive
    # (D:) is tried before anything else on drive C.
    near = [exe_dir.parent / "FischMacro-data", Path(exe_dir.anchor) / "FischMacro-data"]
    if _same_drive(exe_dir, _system_drive()):
        near = [d / "FischMacro-data" for d in _other_fixed_drives()] + near
    for base in dict.fromkeys(near):  # same order, no repeats
        if _writable(base):
            return base
    return None


def _system_drive() -> Path:
    return Path((os.environ.get("SystemDrive") or "C:") + "\\")


def _same_drive(a: Path, b: Path) -> bool:
    return a.anchor.lower() == b.anchor.lower()


def _other_fixed_drives() -> list[Path]:
    """Fixed (internal) drives other than the system drive, e.g. D:\\. Windows only."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        import string
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        system = _system_drive().anchor.lower()
        out = []
        for i, letter in enumerate(string.ascii_uppercase):
            root = f"{letter}:\\"
            if mask >> i & 1 and root.lower() != system and ctypes.windll.kernel32.GetDriveTypeW(root) == 3:
                out.append(Path(root))
        return out
    except Exception:  # noqa: BLE001
        return []


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
    """Older versions, or a run where the app's folder could not be written, kept everything in
    %APPDATA%\\FischMacro or a FischMacro-data folder (e.g. C:\\FischMacro-data). Bring it over to the folder in use
    - profiles, settings, statistics and logs it does not have yet - and then remove the old folder."""
    if sys.platform != "win32":
        return
    exe_dir = Path(sys.executable).resolve().parent
    olds = [_user_folder(), exe_dir / "data", exe_dir.parent / "FischMacro-data",
            Path(exe_dir.anchor) / "FischMacro-data", _system_drive() / "FischMacro-data"]
    for old in dict.fromkeys(olds):
        _move_folder(old, base)


def _move_folder(old: Path, base: Path) -> None:
    try:
        if not old.is_dir() or old.resolve() == base.resolve() or base.resolve().is_relative_to(old.resolve()):
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
