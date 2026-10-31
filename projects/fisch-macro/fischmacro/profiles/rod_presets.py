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
              "Metronome: clicks only when the pendulum is over a lit section (every click off a section costs "
              "5% progress, so the bar is left alone). Pick the mode on the Fishing page."),
    RodPreset("Stellarwave Melody", ("stellarwave",),
              {"minigame.kind": "stellarwave", "minigame.keep_reeling": True, "minigame.action": "click"},
              "Zodiac wheel: 12 signs; the one asked for is shown above the bar (Aries to Pisces order) and "
              "the macro clicks the matching sign on the bar, checking each click. Calibrate the target sign "
              "and the sign row once. Clicking is from the community wiki - verify in game."),
    RodPreset("Halibut Harpoon", ("halibut", "harpoon"),
              {"minigame.kind": "halibut", "minigame.keep_reeling": True},
              "Harpoons land on spots marked '!' and add progress while the fish is in the bar. Nothing is "
              "clicked; the '!' marks are kept from being mistaken for the fish."),
    RodPreset("Pinion's Aria", ("pinion",),
              {"reel.mode": "precision", "reel.mpc_margin": 0.2},
              "Very low control and resilience: precision tracking with a wider safety margin."),
    RodPreset("Migurod", ("migurod", "migu"),
              {"reel.mode": "precision", "reel.mpc_margin": 0.25, "minigame.kind": "migu",
               "minigame.keep_reeling": True},
              "Extremely low control: precision tracking with a large safety margin. Presses Shift when the "
              "timing bar's pointer is in the middle. Slashes are not dodged automatically (not documented)."),
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
