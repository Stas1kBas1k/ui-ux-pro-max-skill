"""Switching the Lullaby rod's mode without ever guessing.

The mode key (Q) cycles the modes. The old code pressed it until the wanted name was read, and pressed
it blindly when the screen could not be read - so pressing Start could move the rod off a mode the user
had picked by hand. Now a press only happens when the current mode's name is on screen, and every
press must be followed by a different mode name, or switching stops.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fischmacro.game_data import LULLABY_MODES
from fischmacro.vision.ocr import find_keywords

MODE_NAMES = [m[0] for m in LULLABY_MODES]


def visible_lullaby_mode(text: str) -> str:
    """The one Lullaby mode named in the text, or "" when none or several (an open menu) are named."""
    found = find_keywords(text, MODE_NAMES)
    return found[0] if len(found) == 1 else ""


@dataclass
class SwitchResult:
    ok: bool
    presses: int
    message: str


def switch_lullaby_mode(want: str, read: Callable[[], str], press: Callable[[], bool],
                        wait: Callable[[float], bool], settle: float = 0.8) -> SwitchResult:
    """Press the mode key until ``want`` is shown. ``read`` returns the visible mode ("" if unreadable),
    ``press`` sends one key press, ``wait`` sleeps and returns True when aborted."""
    current = read()
    if current == want:
        return SwitchResult(True, 0, f"{want} (already set)")
    if not current:
        return SwitchResult(False, 0, f"no mode name readable on screen - left as is (wanted {want}). "
                                      "Switch it by hand, or check that the mode name is visible")
    seen = {current}
    presses = 0
    for _ in range(len(MODE_NAMES)):
        if not press():
            return SwitchResult(False, presses, "input refused (paused or stopped)")
        presses += 1
        if wait(settle):
            return SwitchResult(False, presses, "stopped while switching")
        now = read()
        if now == want:
            return SwitchResult(True, presses, f"{want} ({presses} press{'es' if presses > 1 else ''})")
        if not now or now == current:
            return SwitchResult(False, presses, f"the mode did not change after pressing the key - stopped at "
                                                f"{now or 'an unreadable mode'} (wanted {want})")
        if now in seen:
            return SwitchResult(False, presses, f"cycled through every mode without seeing {want}")
        seen.add(now)
        current = now
    return SwitchResult(False, presses, f"gave up after {presses} presses (wanted {want})")
