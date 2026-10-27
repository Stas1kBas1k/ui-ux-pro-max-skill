"""Mouse/keyboard output with held-input tracking and a hard kill switch.

All automation input goes through :class:`InputController`. It records every
button/key currently held so ``release_all`` can always restore a clean state,
and ``disable`` makes it refuse further input until explicitly re-enabled -
that is what the emergency stop uses.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class InputBackend:
    name = "base"

    def move(self, x: int, y: int) -> None: ...
    def button(self, down: bool, button: str = "left") -> None: ...
    def key(self, down: bool, key: str) -> None: ...


@dataclass
class RecordingBackend(InputBackend):
    """Sends nothing; records events. Used by tests and dry runs."""
    name: str = "recording"
    events: list[tuple] = field(default_factory=list)

    def move(self, x, y):
        self.events.append(("move", x, y))

    def button(self, down, button="left"):
        self.events.append(("down" if down else "up", button))

    def key(self, down, key):
        self.events.append(("key_down" if down else "key_up", key))


class PynputBackend(InputBackend):
    name = "pynput"

    def __init__(self) -> None:
        from pynput import keyboard, mouse  # imported lazily: needs a desktop session
        self._kb_mod = keyboard
        self._mouse = mouse.Controller()
        self._kb = keyboard.Controller()
        self._buttons = {"left": mouse.Button.left, "right": mouse.Button.right, "middle": mouse.Button.middle}

    def _key(self, name: str):
        name = name.strip()
        lower = name.lower()
        aliases = {"return": "enter", "esc": "esc", "escape": "esc", "spacebar": "space", "ctrl": "ctrl_l",
                   "control": "ctrl_l", "alt": "alt_l", "shift": "shift_l", "win": "cmd", "backslash": "\\"}
        lower = aliases.get(lower, lower)
        if len(lower) == 1:
            return self._kb_mod.KeyCode.from_char(lower)
        try:
            return self._kb_mod.Key[lower]
        except KeyError as exc:
            raise ValueError(f"Unknown key name: {name!r}") from exc

    def move(self, x, y):
        self._mouse.position = (int(x), int(y))

    def button(self, down, button="left"):
        b = self._buttons.get(button, self._buttons["left"])
        (self._mouse.press if down else self._mouse.release)(b)

    def key(self, down, key):
        k = self._key(key)
        (self._kb.press if down else self._kb.release)(k)


class InputController:
    def __init__(self, backend: InputBackend | None = None, click_hold_ms: int = 25,
                 key_hold_ms: int = 35, mouse_nudge: bool = True):
        self.backend = backend or RecordingBackend()
        self.click_hold_ms = click_hold_ms
        self.key_hold_ms = key_hold_ms
        self.mouse_nudge = mouse_nudge
        self._lock = threading.RLock()
        self._held_buttons: set[str] = set()
        self._held_keys: set[str] = set()
        self._enabled = True
        self.sent = 0

    # -- state
    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        """Kill switch: release everything and ignore input until :meth:`enable`."""
        with self._lock:
            self._enabled = False
            self._release_locked()

    def is_held(self, button: str = "left") -> bool:
        return button in self._held_buttons

    def held(self) -> tuple[set[str], set[str]]:
        with self._lock:
            return set(self._held_buttons), set(self._held_keys)

    # -- mouse
    def move_to(self, x: int, y: int) -> bool:
        with self._lock:
            if not self._enabled:
                return False
            self.backend.move(x, y)
            return True

    def mouse_down(self, button: str = "left") -> bool:
        with self._lock:
            if not self._enabled:
                return False
            if button not in self._held_buttons:
                self.backend.button(True, button)
                self._held_buttons.add(button)
                self.sent += 1
            return True

    def mouse_up(self, button: str = "left") -> None:
        # Releasing is always allowed, even when disabled.
        with self._lock:
            if button in self._held_buttons:
                self._held_buttons.discard(button)
                self._safe(lambda: self.backend.button(False, button))
                self.sent += 1

    def click(self, x: int | None = None, y: int | None = None, button: str = "left") -> bool:
        with self._lock:
            if not self._enabled:
                return False
            if x is not None and y is not None:
                if self.mouse_nudge:
                    self.backend.move(x + 1, y)
                self.backend.move(x, y)
            if not self.mouse_down(button):
                return False
        time.sleep(self.click_hold_ms / 1000.0)
        self.mouse_up(button)
        return True

    # -- keyboard
    def key_down(self, key: str) -> bool:
        with self._lock:
            if not self._enabled:
                return False
            if key not in self._held_keys:
                self.backend.key(True, key)
                self._held_keys.add(key)
                self.sent += 1
            return True

    def key_up(self, key: str) -> None:
        with self._lock:
            if key in self._held_keys:
                self._held_keys.discard(key)
                self._safe(lambda: self.backend.key(False, key))
                self.sent += 1

    def press_key(self, key: str) -> bool:
        if not key or not self.key_down(key):
            return False
        time.sleep(self.key_hold_ms / 1000.0)
        self.key_up(key)
        return True

    # -- safety
    def release_all(self) -> None:
        with self._lock:
            self._release_locked()

    def _release_locked(self) -> None:
        for b in list(self._held_buttons):
            self._held_buttons.discard(b)
            self._safe(lambda b=b: self.backend.button(False, b))
        for k in list(self._held_keys):
            self._held_keys.discard(k)
            self._safe(lambda k=k: self.backend.key(False, k))

    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a failed release must not stop other releases
            log.error("Input release failed: %s", exc)


def create_backend(simulated_game=None) -> InputBackend:
    """Real input for live play, the simulator for test mode, recording as last resort."""
    if simulated_game is not None:
        from fischmacro.simulation.game import SimulatedInputBackend
        return SimulatedInputBackend(simulated_game)
    try:
        return PynputBackend()
    except Exception as exc:  # noqa: BLE001
        log.warning("Real input unavailable (%s); using a recording backend - no input will be sent.", exc)
        return RecordingBackend()
