"""Handlers for rod mechanics found on the Fisch wiki (see docs/SPECIAL_RODS.md for the full research table).

Each handler is called every reeling frame by the minigame solver (``s``) and logs once per catch when it
becomes active, so the log shows which special handler ran.

* falling      - Pinion's Aria notes, Santa's Miracle presents, Starshell shells: the steering itself moves the
                 bar under the next object (fsm.py + vision/falling.py); this only logs what it sees.
* special_key  - Dutchman's Rod: "the player can activate Spectral Barrage with their Special Action Keybind
                 while fishing, launching one fish" (wiki). The keybind is the player's own, so nothing is
                 pressed until it is set.
"""
from __future__ import annotations


def _activated(s, now: float, what: str) -> None:
    if not getattr(s, "special_logged", False):
        s.special_logged = True
        s._note(now, what)


def falling_update(s, obs, now: float) -> None:
    if obs.drops:
        _activated(s, now, "catch falling objects")


def special_key_update(s, obs, now: float) -> None:
    key = (s.cfg.special_key or "").strip()
    if not key or not obs.reel.ui_present:
        return
    _activated(s, now, f"Special Action key '{key}' every {s.cfg.special_interval:g} s")
    if now - getattr(s, "last_special", -1e9) >= s.cfg.special_interval and now - (s.t_start or now) >= 0.5:
        s.last_special = now
        s.fsm.input.press_key(key)
        s.actions += 1
