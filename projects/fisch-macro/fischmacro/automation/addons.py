"""Fishing add-ons: Sovereign recharge, Auto Totem, Auto Appraise, potion and Astral Activator.

Readouts (rod power, weather, time of day, surge) come from OCR watchers. The
actions run only at safe points between catches, through the routine runner,
so pause / focus loss / emergency stop interrupt them like any other input.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from fischmacro.game_data import SURGE_TOTEM, SURGES, TIME_TOTEM, WEATHER_TOTEM, WEATHERS
from fischmacro.profiles.schema import AddonsConfig, Routine, RoutineStep
from fischmacro.vision.ocr import find_keywords, fuzzy_contains

log = logging.getLogger(__name__)


@dataclass
class WorldState:
    weather: str = ""
    time: str = ""      # Day | Night
    surge: str = ""     # Shiny | Sparkling | Mutation | "" (none)
    updated: float = 0.0
    power: int | None = None
    power_updated: float = 0.0


def parse_power(text: str) -> int | None:
    """'Power 87%' / '87 %' / '87/100' -> 87."""
    m = re.search(r"(\d{1,3})\s*(?:%|/\s*100)", text)
    if not m:
        m = re.search(r"\b(\d{1,3})\b", text)
    if not m:
        return None
    v = int(m.group(1))
    return v if 0 <= v <= 100 else None


def parse_world(text: str) -> tuple[str, str, str]:
    """(weather, time, surge) found in a block of on-screen text. Empty strings when not found."""
    t = text.lower()
    weather = ""
    # longer names first so "Raging Squall" wins over "Rain"
    for name, _, _, words in sorted(WEATHERS, key=lambda w: -max(len(x) for x in w[3])):
        if any(fuzzy_contains(t, w) for w in words):
            weather = name
            break
    tod = ""
    if fuzzy_contains(t, "night"):
        tod = "Night"
    elif fuzzy_contains(t, "day") or fuzzy_contains(t, "morning") or fuzzy_contains(t, "noon"):
        tod = "Day"
    else:
        m = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?", t)
        if m:
            h = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0) if m.group(3) else int(m.group(1))
            tod = "Day" if 6 <= h < 18 else "Night"
    surge = next((name for name, _, _, words in SURGES if find_keywords(t, list(words))), "")
    return weather, tod, surge


@dataclass
class AddonsService:
    cfg: AddonsConfig
    world: WorldState = field(default_factory=WorldState)
    last_used: dict[str, float] = field(default_factory=dict)
    session_start: float = field(default_factory=time.monotonic)

    # -- readouts (called from the watcher thread)
    def on_world_text(self, text: str, now: float) -> None:
        weather, tod, surge = parse_world(text)
        w = self.world
        if weather:
            w.weather = weather
        if tod:
            w.time = tod
        w.surge = surge
        w.updated = now

    def on_power_text(self, text: str, now: float) -> None:
        p = parse_power(text)
        if p is not None:
            self.world.power, self.world.power_updated = p, now

    def reset(self, now: float) -> None:
        self.last_used.clear()
        self.session_start = now

    # -- decisions (pure, testable)
    def _due(self, key: str, now: float, every_min: float) -> bool:
        last = self.last_used.get(key, self.session_start)
        return now - last >= every_min * 60

    def plan(self, now: float) -> list[tuple[str, Routine]]:
        """Routines to run now, in order, with a reason."""
        c, w, out = self.cfg, self.world, []
        s = c.sovereign
        if s.enabled and w.power is not None and now - w.power_updated < 60 and w.power < s.recharge_below:
            out.append((f"Sovereign power {w.power}% (below {s.recharge_below}%)", self.recharge_routine()))
        t = c.totem
        if t.enabled and w.updated and now - w.updated < 120:
            cooldown_ok = lambda k: now - self.last_used.get(k, -1e9) >= t.cooldown_min * 60  # noqa: E731
            if t.weather in WEATHER_TOTEM and w.weather and w.weather != t.weather and cooldown_ok("weather"):
                out.append((f"Weather is {w.weather}, holding {t.weather}", self._use("weather", WEATHER_TOTEM[t.weather])))
            if t.time in ("Day", "Night") and w.time and w.time != t.time and cooldown_ok("time"):
                out.append((f"It is {w.time}, want {t.time}", self._use("time", TIME_TOTEM)))
            if t.surge in SURGE_TOTEM and w.surge != t.surge and cooldown_ok("surge"):
                out.append((f"No {t.surge} surge active", self._use("surge", SURGE_TOTEM[t.surge])))
        for key, item in (("potion", c.potion), ("astral", c.astral)):
            if item.enabled and item.item and self._due(key, now, item.every_min):
                out.append((f"{item.item} every {item.every_min:g} min", self._use(key, item.item)))
        return out

    def _use(self, key: str, item: str) -> Routine:
        r = Routine(f"{key}:{item}", enabled=True, steps=[RoutineStep("use_item", item), RoutineStep("wait", seconds=1.5)])
        r.note = key
        return r

    def recharge_routine(self) -> Routine:
        s = self.cfg.sovereign
        return Routine("Sovereign recharge", enabled=True, note="sovereign",
                       steps=[RoutineStep("use_item", s.relic), RoutineStep("wait", seconds=1.5)])

    def appraise_routine(self) -> Routine:
        a = self.cfg.appraise
        steps = [RoutineStep("key", "e"), RoutineStep("wait", seconds=0.8)] if a.mode == "Appraiser NPC" else []
        steps += [RoutineStep("click_text", "Appraise", seconds=4), RoutineStep("wait", seconds=2.0)]
        return Routine("Auto Appraise", enabled=True, steps=steps, repeat_until="|".join(a.traits),
                       max_repeats=max(1, a.max_tries), reequip_rod=False)

    def mark(self, routine: Routine, now: float) -> None:
        self.last_used[routine.note] = now
