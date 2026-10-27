"""Global hotkeys with auto-repeat suppression and conflict detection."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

MODIFIERS = ("ctrl", "alt", "shift")
_MOD_ALIASES = {
    "ctrl_l": "ctrl", "ctrl_r": "ctrl", "control": "ctrl",
    "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "shift_l": "shift", "shift_r": "shift",
}
VALID_KEYS = {f"f{i}" for i in range(1, 25)} | set("abcdefghijklmnopqrstuvwxyz0123456789") | {
    "insert", "delete", "home", "end", "page_up", "page_down", "pause", "scroll_lock", "print_screen",
    "num_lock", "space", "enter", "tab", "backspace", "esc", "up", "down", "left", "right",
    "`", "-", "=", "[", "]", "\\", ";", "'", ",", ".", "/",
}


class HotkeyError(ValueError):
    pass


def normalize_key(name: str) -> str:
    name = name.strip().lower().replace(" ", "_")
    name = {"return": "enter", "escape": "esc", "del": "delete", "ins": "insert", "pgup": "page_up",
            "pgdn": "page_down", "prtsc": "print_screen", "control": "ctrl"}.get(name, name)
    return _MOD_ALIASES.get(name, name)


def normalize_combo(combo: str) -> str:
    """'Ctrl + F6' -> 'ctrl+f6'. Raises HotkeyError for invalid combos."""
    if not combo or not combo.strip():
        raise HotkeyError("Hotkey is empty")
    raw = combo.strip().lower()
    # Allow a literal '+' key at the end, e.g. 'ctrl++'.
    parts = [p for p in raw.split("+") if p.strip()] if raw != "+" else ["+"]
    keys = [normalize_key(p) for p in parts]
    mods = sorted({k for k in keys if k in MODIFIERS}, key=MODIFIERS.index)
    main = [k for k in keys if k not in MODIFIERS]
    if len(main) != 1:
        raise HotkeyError(f"'{combo}' must contain exactly one non-modifier key")
    if main[0] not in VALID_KEYS:
        raise HotkeyError(f"'{main[0]}' is not a supported hotkey key")
    return "+".join(mods + main)


def find_conflicts(bindings: dict[str, str]) -> dict[str, list[str]]:
    """combo -> actions, for every combo bound to more than one action."""
    seen: dict[str, list[str]] = {}
    for action, combo in bindings.items():
        try:
            norm = normalize_combo(combo)
        except HotkeyError:
            continue
        seen.setdefault(norm, []).append(action)
    return {k: v for k, v in seen.items() if len(v) > 1}


def reserved_conflicts(bindings: dict[str, str], game_keys: dict[str, str]) -> list[str]:
    """Warn when a hotkey equals a key the automation itself presses in-game."""
    out = []
    used = {}
    for label, key in game_keys.items():
        if key:
            try:
                used[normalize_combo(key)] = label
            except HotkeyError:
                pass
    for action, combo in bindings.items():
        try:
            norm = normalize_combo(combo)
        except HotkeyError:
            continue
        if norm in used:
            out.append(f"'{combo}' ({action}) is also pressed by the automation as {used[norm]}")
    return out


class HotkeyManager:
    """Maps key events to actions. Fires once per physical press.

    ``handle_press``/``handle_release`` contain all the logic and are fed either
    by a pynput global listener or directly by tests.
    """

    def __init__(self, bindings: dict[str, str], callback: Callable[[str], None], debounce: float = 0.25,
                 clock: Callable[[], float] = time.monotonic):
        self.callback = callback
        self.debounce = debounce
        self.clock = clock
        self._lock = threading.Lock()
        self._mods: set[str] = set()
        self._down: set[str] = set()
        self._last_fire: dict[str, float] = {}
        self._listener = None
        self.enabled = True
        self.bindings: dict[str, str] = {}
        self.set_bindings(bindings)

    def set_bindings(self, bindings: dict[str, str]) -> list[str]:
        """Apply bindings; returns errors for invalid or duplicate ones (those are skipped)."""
        errors, table = [], {}
        for action, combo in bindings.items():
            try:
                norm = normalize_combo(combo)
            except HotkeyError as exc:
                errors.append(f"{action}: {exc}")
                continue
            if norm in table:
                errors.append(f"{action}: '{norm}' already used by {table[norm]}")
                continue
            table[norm] = action
        with self._lock:
            self._table = table
            self.bindings = dict(bindings)
        return errors

    def handle_press(self, key: str) -> str | None:
        key = normalize_key(key)
        with self._lock:
            if key in MODIFIERS:
                self._mods.add(key)
                return None
            if key in self._down:  # OS auto-repeat while held
                return None
            self._down.add(key)
            combo = "+".join([m for m in MODIFIERS if m in self._mods] + [key])
            action = self._table.get(combo)
            if action is None or not self.enabled:
                return None
            now = self.clock()
            if now - self._last_fire.get(action, -1e9) < self.debounce:
                return None
            self._last_fire[action] = now
        try:
            self.callback(action)
        except Exception:  # noqa: BLE001
            log.exception("Hotkey action %s failed", action)
        return action

    def handle_release(self, key: str) -> None:
        key = normalize_key(key)
        with self._lock:
            self._mods.discard(key)
            self._down.discard(key)

    # -- global listener
    def start(self) -> bool:
        """Start the global keyboard listener. Returns False if unavailable."""
        try:
            from pynput import keyboard
        except Exception as exc:  # noqa: BLE001
            log.warning("Global hotkeys unavailable: %s", exc)
            return False

        def name_of(k) -> str | None:
            if isinstance(k, keyboard.Key):
                return k.name
            char = getattr(k, "char", None)
            if char:
                if len(char) == 1 and ord(char) < 32:  # ctrl+letter arrives as a control char
                    return chr(ord(char) + 96)
                return char
            vk = getattr(k, "vk", None)
            if vk is not None and 0x70 <= vk <= 0x87:
                return f"f{vk - 0x6F}"
            if vk is not None and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
                return chr(vk).lower()
            return None

        def on_press(k):
            n = name_of(k)
            if n:
                self.handle_press(n)

        def on_release(k):
            n = name_of(k)
            if n:
                self.handle_release(n)

        try:
            self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._listener.daemon = True
            self._listener.start()
        except Exception as exc:  # noqa: BLE001
            log.warning("Global hotkey listener failed to start: %s", exc)
            self._listener = None
            return False
        log.info("Global hotkeys active: %s", ", ".join(f"{a}={c}" for c, a in self._table.items()))
        return True

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # noqa: BLE001
                pass
            self._listener = None

    @property
    def active(self) -> bool:
        return self._listener is not None
