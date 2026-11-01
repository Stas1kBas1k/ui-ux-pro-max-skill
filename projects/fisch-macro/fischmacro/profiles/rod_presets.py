"""Starting settings for rods with special minigames or extreme stats.

Applied when a rod is detected for the first time (auto profiles) or from the
Profiles page. Every value stays editable. Rod details come from community
guides and need checking in game; entries marked ``verify`` are educated guesses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RodPreset:
    name: str
    match: tuple[str, ...]                # lowercase words that identify the rod's name
    settings: dict[str, object] = field(default_factory=dict)
    note: str = ""
    verify: bool = True


PRESETS: list[RodPreset] = [
    RodPreset("Lullaby", ("lullaby",),
              {"minigame.kind": "lullaby", "minigame.keep_reeling": False},
              "Metronome: clicks only while the pendulum is over the lit part of the half-moon (a click on the "
              "red part is a miss). The catch bar is left alone. If clicks land a little late or early, change "
              "Click timing."),
    RodPreset("Stellarwave Melody", ("stellarwave",),
              {"minigame.kind": "stellarwave", "minigame.keep_reeling": True, "detection.reel_mode": "capsule"},
              "Zodiac strip: reels the bright capsule bar, and picks the signs in order (Aries..Pisces) by "
              "keeping the cursor on the next sign and clicking it; each pick is checked by its star lighting "
              "up. Built from a real recording; works with skins because the signs are matched against the "
              "top row of the same screen."),
    RodPreset("Halibut Harpoon", ("halibut", "harpoon"),
              {"minigame.kind": "halibut", "minigame.keep_reeling": True},
              "Harpoons land on spots marked '!' and add progress while the fish is in the bar. Nothing is "
              "clicked; the '!' marks are kept from being mistaken for the fish."),
    RodPreset("Pinion's Aria", ("pinion",),
              {"reel.mode": "precision", "reel.mpc_margin": 0.2, "minigame.kind": "falling",
               "minigame.keep_reeling": True},
              "Notes fall across the bar: the bar moves under each one when the fish stays inside (a missed "
              "note costs 10%). Very low control: precision tracking with a wider safety margin."),
    RodPreset("Santa's Miracle Rod", ("santa s miracle", "santas miracle"),
              {"minigame.kind": "falling", "minigame.keep_reeling": True},
              "Presents fall across the bar: the bar moves under each one when the fish stays inside (+10%)."),
    RodPreset("Starshell Rod", ("starshell",),
              {"minigame.kind": "falling", "minigame.keep_reeling": True},
              "Shells fall onto the bar every 4 s: the bar moves under each one when the fish stays inside."),
    RodPreset("Dutchman's Rod", ("dutchman",),
              {"minigame.kind": "special_key", "minigame.keep_reeling": True},
              "Spectral Barrage: set your Special Action key and it is pressed during the catch to launch a "
              "stored fish."),
    RodPreset("Migurod", ("migurod", "migu"),
              {"reel.mode": "precision", "reel.mpc_margin": 0.25, "minigame.kind": "migu",
               "minigame.keep_reeling": True},
              "Extremely low control: precision tracking with a large safety margin. Presses Shift when the "
              "timing bar's pointer is in the middle. Keeps the bar away from the slash marks."),
    RodPreset("Tryhard / low resilience", ("tryhard",),
              {"reel.mode": "precision", "reel.mpc_margin": 0.2},
              "Any rod with a tiny bar or fast progress drain."),
]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower())


def find_preset(rod_name: str) -> RodPreset | None:
    from fischmacro.vision.ocr import fuzzy_contains
    words = _norm(rod_name)
    for p in PRESETS:
        if any(m in words or fuzzy_contains(words, m) for m in p.match):
            return p
    return None


def apply_preset(profile, preset: RodPreset) -> list[str]:
    changed = []
    for path, value in preset.settings.items():
        section, attr = path.split(".")
        obj = getattr(profile, section)
        if getattr(obj, attr) != value:
            setattr(obj, attr, value)
            changed.append(path)
    return changed
