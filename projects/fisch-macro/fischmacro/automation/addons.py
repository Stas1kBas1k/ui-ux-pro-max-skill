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
from enum import Enum

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
    """'Power 87%' / '87 %' / '87/100' -> 87. A bare number is never taken: the old fallback read the bait
    count or a hotbar slot number as the rod power and recharged over and over."""
    # The real readout is "90% Power", under an enchant line full of other percentages ("10% chance for
    # Paradise mutation, +15% Luck, +5% Fish Weight"): a number next to the word Power wins, and with
    # several percentages and none next to Power, nothing is read.
    m = re.search(r"(\d{1,3})\s*%\s*power|power\W{0,3}(\d{1,3})\s*%", text, re.IGNORECASE)
    if m:
        v = int(m.group(1) or m.group(2))
        return v if 0 <= v <= 100 else None
    if re.search(r"chance|luck|weight|mutation|speed", text, re.IGNORECASE):
        return None  # only the enchant description is in the box
    found = re.findall(r"(?<!\d)(\d{1,3})\s*(?:%|/\s*100\b)", text)
    if len(found) != 1:
        return None
    v = int(found[0])
    return v if 0 <= v <= 100 else None


class Recharge(str, Enum):
    IDLE = "idle"
    IN_PROGRESS = "in progress"     # a relic was used, waiting for the power to go up
    COMPLETE = "complete"
    FAILED = "failed"
    COOLDOWN = "cooldown"           # after a failure: no attempts for a while
    DISABLED = "disabled"           # failed too often this session


@dataclass
class RechargeMachine:
    """Sovereign recharge with hard limits, so a bad reading can never spam the inventory.

    One attempt uses at most ``max_relics`` relics, and each must be followed by a higher power reading
    (verified). A relic that changes nothing fails the attempt and starts a cooldown; after
    ``max_failures`` failures the add-on stops for the session.
    """
    max_relics: int = 4
    confirm_s: float = 8.0
    cooldown_s: float = 300.0
    max_failures: int = 3
    state: Recharge = Recharge.IDLE
    failures: int = 0
    relics_used: int = 0
    until: float = 0.0
    last_message: str = ""
    history: list[tuple[float, str]] = field(default_factory=list)

    def _to(self, state: Recharge, now: float, msg: str) -> None:
        self.state, self.last_message = state, msg
        self.history.append((now, f"{state.value}: {msg}"))
        del self.history[:-30]

    def reset(self) -> None:
        self.state, self.failures, self.relics_used, self.until, self.last_message = Recharge.IDLE, 0, 0, 0.0, ""
        self.history.clear()

    def wanted(self, power: int | None, power_age: float, below: int, now: float) -> bool:
        """Start an attempt? Needs a fresh, stable reading under the threshold and no cooldown."""
        if self.state == Recharge.DISABLED:
            return False
        if self.state == Recharge.COOLDOWN and now < self.until:
            return False
        if self.state in (Recharge.COOLDOWN, Recharge.COMPLETE, Recharge.FAILED):
            self.state = Recharge.IDLE
        return self.state == Recharge.IDLE and power is not None and power_age < 30 and power < below

    def run(self, use_relic, read_power, wait, target: int, now_fn) -> bool:
        """Do one attempt. ``use_relic()`` -> bool, ``read_power()`` -> (power, updated_at) of the latest
        stable reading, ``wait(s)`` -> True when aborted. Returns False only when aborted."""
        self.relics_used = 0
        self._to(Recharge.IN_PROGRESS, now_fn(), "using relic")
        power, _ = read_power()
        for _ in range(self.max_relics):
            _, seen_at = read_power()
            if not use_relic():
                self._to(Recharge.FAILED, now_fn(), "the relic could not be used (input refused or not found)")
                return self._fail(now_fn())
            self.relics_used += 1
            deadline = now_fn() + self.confirm_s
            new, at = read_power()
            while at <= seen_at and now_fn() < deadline:
                if wait(0.3):
                    self._to(Recharge.IDLE, now_fn(), "stopped")
                    return False
                new, at = read_power()
            if at <= seen_at or new is None:
                self._to(Recharge.FAILED, now_fn(), "no new power reading after the relic - check the power region")
                return self._fail(now_fn())
            if power is not None and new <= power:
                self._to(Recharge.FAILED, now_fn(), f"power did not go up ({power}% -> {new}%)")
                return self._fail(now_fn())
            power = new
            if power >= target:
                self.failures = 0
                self._to(Recharge.COMPLETE, now_fn(), f"recharged to {power}% with {self.relics_used} relic(s)")
                return True
        self._to(Recharge.COMPLETE, now_fn(), f"at {power}% after {self.relics_used} relics (limit per attempt)")
        return True

    def _fail(self, now: float) -> bool:
        self.failures += 1
        if self.failures >= self.max_failures:
            self._to(Recharge.DISABLED, now, f"stopped for this session after {self.failures} failed attempts")
        else:
            self.until = now + self.cooldown_s
            self.state = Recharge.COOLDOWN
        return True


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
    recharge: RechargeMachine = field(default_factory=RechargeMachine)
    _power_candidate: int | None = None

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
        """Take a power reading only when two reads in a row agree (one misread must not start a recharge)."""
        p = parse_power(text)
        if p is None:
            self._power_candidate = None
            return
        prev = self._power_candidate
        self._power_candidate = p
        if prev is not None and abs(prev - p) <= 2:
            self.world.power, self.world.power_updated = p, now

    def reset(self, now: float) -> None:
        self.last_used.clear()
        self.session_start = now
        self.recharge.reset()

    # -- decisions (pure, testable)
    def _due(self, key: str, now: float, every_min: float) -> bool:
        last = self.last_used.get(key, self.session_start)
        return now - last >= every_min * 60

    def plan(self, now: float) -> list[tuple[str, Routine]]:
        """Routines to run now, in order, with a reason."""
        c, w, out = self.cfg, self.world, []
        s = c.sovereign
        if s.enabled and self.recharge.wanted(w.power, now - w.power_updated, s.recharge_below, now):
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
