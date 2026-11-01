"""Rod Library logic (no UI): which profile belongs to which rod and skin, favourites, recents, drafts.

Naming: a rod's profile is called after the rod ("Lullaby"); a skin gets its own profile only when it
needs different detection ("Lullaby - Toothly Interstellar"); copies are "Lullaby - Custom 2". Screen
calibration (regions) is shared: a new rod profile starts from the active profile's regions, with clean
colours and the rod's recommended settings.
"""
from __future__ import annotations

import copy
from functools import lru_cache
import re
from dataclasses import dataclass

from fischmacro.game_data import ALL_RODS
from fischmacro.profiles.manager import ProfileError, ProfileManager
from fischmacro.profiles.rod_presets import apply_preset, find_preset
from fischmacro.profiles.schema import DetectionConfig, LibraryConfig, Profile, to_dict
from fischmacro.rods import behaviour_for

DEFAULT_SKIN = "Default"
# Rods with the normal catch bar and no tuned settings share one configuration under this name.
BASIC_GROUP = "Basic Rods"



def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


@dataclass
class RodInfo:
    name: str
    kind: str                 # rod minigame kind the preset uses ("none" for normal rods)
    special: bool
    preset_note: str
    status: str               # how well it is verified: "real screenshot" | "simulated" | "unconfirmed"
    profiles: list[str]
    favourite: bool
    recent_rank: int | None   # 0 = last used


@lru_cache(maxsize=512)
def recommended_kind(rod: str) -> tuple[str, str]:
    preset = find_preset(rod)
    if preset is None:
        return "none", ""
    p = Profile()
    apply_preset(p, preset)
    return p.minigame.kind, preset.note


def is_basic(rod: str) -> bool:
    return rod != BASIC_GROUP and recommended_kind(rod) == ("none", "")


def basic_rods() -> list[str]:
    return [r for r in ALL_RODS if is_basic(r)]


class RodLibrary:
    def __init__(self, profiles: ProfileManager, cfg: LibraryConfig):
        self.profiles = profiles
        self.cfg = cfg
        self._index: dict[str, list[str]] | None = None

    # -- profiles per rod
    def refresh(self) -> None:
        self._index = None

    def _rod_index(self) -> dict[str, list[str]]:
        if self._index is None:
            idx: dict[str, list[str]] = {}
            for name in self.profiles.names():
                try:
                    p = self.profiles.load(name)
                except ProfileError:
                    continue
                rod = _norm(p.equipment.rod_name)
                if rod and rod != "any rod":
                    idx.setdefault(rod, []).append(name)
            self._index = idx
        return self._index

    def profiles_for(self, rod: str) -> list[str]:
        return sorted(self._rod_index().get(_norm(rod), []), key=lambda n: (len(n), n))

    def skins_for(self, rod: str) -> list[str]:
        skins = [DEFAULT_SKIN]
        for name in self.profiles_for(rod):
            try:
                sk = self.profiles.load(name).equipment.skin.strip()
            except ProfileError:
                continue
            if sk and sk not in skins:
                skins.append(sk)
        for sk in self.cfg.skins.get(rod, []):
            if sk not in skins:
                skins.append(sk)
        return skins

    def info(self, rod: str) -> RodInfo:
        kind, note = recommended_kind(rod)
        b = behaviour_for(kind)
        recent = self.cfg.recent.index(rod) if rod in self.cfg.recent else None
        return RodInfo(rod, kind, kind != "none", note, b.status, self.profiles_for(rod),
                       rod in self.cfg.favourites, recent)

    def search(self, text: str = "", category: str = "All") -> list[str]:
        t = _norm(text)
        rods = [r for r in ALL_RODS if not t or t in _norm(r)]
        if category == "Basic rods":
            rods = [r for r in rods if is_basic(r)]
        elif category == "Special minigame":
            rods = [r for r in rods if recommended_kind(r)[0] != "none" or recommended_kind(r)[1]]
        elif category == "Favourites":
            rods = [r for r in rods if r in self.cfg.favourites]
        elif category == "Recent":
            rods = sorted((r for r in rods if r in self.cfg.recent), key=self.cfg.recent.index)
        elif category == "Configured":
            rods = [r for r in rods if self.profiles_for(r)]
        return rods

    def toggle_favourite(self, rod: str) -> bool:
        if rod in self.cfg.favourites:
            self.cfg.favourites.remove(rod)
            return False
        self.cfg.favourites.append(rod)
        return True

    def mark_used(self, rod: str) -> None:
        if rod in self.cfg.recent:
            self.cfg.recent.remove(rod)
        self.cfg.recent.insert(0, rod)
        del self.cfg.recent[12:]

    def add_skin(self, rod: str, skin: str) -> None:
        skin = skin.strip()
        if skin and skin != DEFAULT_SKIN and skin not in self.cfg.skins.setdefault(rod, []):
            self.cfg.skins[rod].append(skin)

    # -- choosing a rod / skin
    def profile_name(self, rod: str, skin: str = DEFAULT_SKIN) -> str:
        return rod if skin in ("", DEFAULT_SKIN) else f"{rod} - {skin}"

    def find_profile(self, rod: str, skin: str = DEFAULT_SKIN) -> str | None:
        """The saved profile for this rod and skin (a skin falls back to the rod's default profile)."""
        names = self.profiles_for(rod)
        want = "" if skin in ("", DEFAULT_SKIN) else skin
        for n in names:
            try:
                if self.profiles.load(n).equipment.skin.strip() == want:
                    return n
            except ProfileError:
                continue
        return None

    def recommended(self, rod: str, skin: str, base: Profile) -> Profile:
        """A fresh profile for the rod: the base profile's screen regions, clean colours, the rod preset."""
        p = copy.deepcopy(base)
        p.name = self.profile_name(rod, skin)
        p.equipment.rod_name = rod
        p.equipment.skin = "" if skin == DEFAULT_SKIN else skin
        p.detection = DetectionConfig()
        fresh = Profile()
        p.reel, p.minigame = fresh.reel, fresh.minigame  # recommended values, then the rod's preset
        preset = find_preset(rod)
        if preset is not None:
            apply_preset(p, preset)
        return p

    def load_or_create(self, rod: str, skin: str, base: Profile) -> tuple[Profile, bool]:
        """(profile, created). Nothing is written to disk here; ``save`` does that."""
        name = self.find_profile(rod, skin)
        if name is not None:
            return self.profiles.load(name), False
        if skin not in ("", DEFAULT_SKIN):
            default = self.find_profile(rod, DEFAULT_SKIN)
            if default is not None:  # a new skin starts from the rod's tuned profile, with clean colours
                p = self.profiles.load(default)
                p.name, p.equipment.skin, p.detection = self.profile_name(rod, skin), skin, DetectionConfig()
                return p, True
        return self.recommended(rod, skin, base), True

    def unique_name(self, wanted: str) -> str:
        names = set(self.profiles.names())
        if wanted not in names:
            return wanted
        i = 2
        while f"{wanted} - Custom {i}" in names:
            i += 1
        return f"{wanted} - Custom {i}"

    def save(self, profile: Profile) -> None:
        self.profiles.save(profile)
        self.refresh()


def is_dirty(draft: Profile, saved: Profile | None) -> bool:
    return saved is None or to_dict(draft) != to_dict(saved)
