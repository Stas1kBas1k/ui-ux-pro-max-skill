"""Profile and application-settings persistence (JSON files in the data folder)."""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import tempfile
from pathlib import Path

from fischmacro import paths
from fischmacro.profiles.schema import AppSettings, Profile, from_dict, to_dict

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
_SAFE = re.compile(r"[^A-Za-z0-9 _.\-()]+")


class ProfileError(Exception):
    pass


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def validate_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ProfileError("Profile name cannot be empty.")
    if _SAFE.search(name):
        raise ProfileError("Use letters, numbers, spaces, dots, dashes, underscores or brackets only.")
    if len(name) > 60:
        raise ProfileError("Profile name is too long (max 60 characters).")
    return name


class ProfileManager:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory else paths.profiles_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.names():
            self.save(Profile(name="Default"))

    def _path(self, name: str) -> Path:
        return self.directory / f"{validate_name(name)}.json"

    def names(self) -> list[str]:
        return sorted((p.stem for p in self.directory.glob("*.json") if not p.name.startswith(".")), key=str.lower)

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    def load(self, name: str) -> Profile:
        path = self._path(name)
        if not path.exists():
            raise ProfileError(f"Profile '{name}' does not exist.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileError(f"Profile '{name}' could not be read: {exc}") from exc
        profile = from_dict(Profile, data.get("profile", data))
        profile.name = name
        return profile

    def save(self, profile: Profile) -> None:
        _atomic_write(self._path(profile.name), {"format": FORMAT_VERSION, "profile": to_dict(profile)})

    def create(self, name: str) -> Profile:
        name = validate_name(name)
        if self.exists(name):
            raise ProfileError(f"Profile '{name}' already exists.")
        profile = Profile(name=name)
        self.save(profile)
        return profile

    def duplicate(self, source: str, new_name: str) -> Profile:
        new_name = validate_name(new_name)
        if self.exists(new_name):
            raise ProfileError(f"Profile '{new_name}' already exists.")
        profile = copy.deepcopy(self.load(source))
        profile.name = new_name
        self.save(profile)
        return profile

    def rename(self, old: str, new: str) -> Profile:
        new = validate_name(new)
        if old == new:
            return self.load(old)
        if self.exists(new):
            raise ProfileError(f"Profile '{new}' already exists.")
        profile = self.load(old)
        profile.name = new
        self.save(profile)
        self._path(old).unlink()
        return profile

    def delete(self, name: str) -> None:
        if len(self.names()) <= 1:
            raise ProfileError("At least one profile must remain.")
        self._path(name).unlink(missing_ok=True)

    def export(self, name: str, destination: Path) -> None:
        profile = self.load(name)
        _atomic_write(Path(destination), {"format": FORMAT_VERSION, "kind": "fischmacro-profile",
                                          "profile": to_dict(profile)})

    def import_file(self, source: Path, name: str | None = None) -> Profile:
        try:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileError(f"Could not read profile file: {exc}") from exc
        if not isinstance(data, dict):
            raise ProfileError("Not a profile file.")
        profile = from_dict(Profile, data.get("profile", data))
        base = validate_name(name or profile.name or Path(source).stem)
        candidate, i = base, 2
        while self.exists(candidate):
            candidate = f"{base} ({i})"
            i += 1
        profile.name = candidate
        self.save(profile)
        return profile


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.settings_file()

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            return from_dict(AppSettings, json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Settings file unreadable (%s); using defaults. Backup kept.", exc)
            try:
                self.path.replace(self.path.with_suffix(".corrupt.json"))
            except OSError:
                pass
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        _atomic_write(self.path, to_dict(settings))
