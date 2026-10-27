"""Windows SendInput backend that sends hardware scan codes.

Roblox reads keyboard input by scan code. Keys sent as virtual-key-only or
Unicode events (what most Python input libraries do for characters such as
``#``) are often ignored by the game, which made shake navigation and hotbar
keys silently fail. This backend sends every key as a scan code (with Shift
when the character needs it) and every mouse action through SendInput, the
same path a physical device takes. It is still ordinary OS input - nothing is
injected into the game process.
"""
from __future__ import annotations

import ctypes
import sys
import time

from fischmacro.input.controller import InputBackend

# US-layout set-1 scan codes. (scan, extended)
_SC: dict[str, tuple[int, bool]] = {
    "esc": (0x01, False), "1": (0x02, False), "2": (0x03, False), "3": (0x04, False), "4": (0x05, False),
    "5": (0x06, False), "6": (0x07, False), "7": (0x08, False), "8": (0x09, False), "9": (0x0A, False),
    "0": (0x0B, False), "-": (0x0C, False), "=": (0x0D, False), "backspace": (0x0E, False), "tab": (0x0F, False),
    "q": (0x10, False), "w": (0x11, False), "e": (0x12, False), "r": (0x13, False), "t": (0x14, False),
    "y": (0x15, False), "u": (0x16, False), "i": (0x17, False), "o": (0x18, False), "p": (0x19, False),
    "[": (0x1A, False), "]": (0x1B, False), "enter": (0x1C, False), "ctrl_l": (0x1D, False), "a": (0x1E, False),
    "s": (0x1F, False), "d": (0x20, False), "f": (0x21, False), "g": (0x22, False), "h": (0x23, False),
    "j": (0x24, False), "k": (0x25, False), "l": (0x26, False), ";": (0x27, False), "'": (0x28, False),
    "`": (0x29, False), "shift_l": (0x2A, False), "\\": (0x2B, False), "z": (0x2C, False), "x": (0x2D, False),
    "c": (0x2E, False), "v": (0x2F, False), "b": (0x30, False), "n": (0x31, False), "m": (0x32, False),
    ",": (0x33, False), ".": (0x34, False), "/": (0x35, False), "shift_r": (0x36, False), "alt_l": (0x38, False),
    "space": (0x39, False), "caps_lock": (0x3A, False),
    "f1": (0x3B, False), "f2": (0x3C, False), "f3": (0x3D, False), "f4": (0x3E, False), "f5": (0x3F, False),
    "f6": (0x40, False), "f7": (0x41, False), "f8": (0x42, False), "f9": (0x43, False), "f10": (0x44, False),
    "f11": (0x57, False), "f12": (0x58, False),
    "home": (0x47, True), "up": (0x48, True), "page_up": (0x49, True), "left": (0x4B, True), "right": (0x4D, True),
    "end": (0x4F, True), "down": (0x50, True), "page_down": (0x51, True), "insert": (0x52, True),
    "delete": (0x53, True), "ctrl_r": (0x1D, True), "alt_r": (0x38, True),
}
# Characters typed with Shift held, mapped to their unshifted key.
_SHIFTED = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
            "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\", ":": ";", '"': "'", "~": "`", "<": ",", ">": ".",
            "?": "/"}
_ALIASES = {"return": "enter", "escape": "esc", "spacebar": "space", "ctrl": "ctrl_l", "control": "ctrl_l",
            "alt": "alt_l", "shift": "shift_l", "backslash": "\\", "grave": "`", "backtick": "`", "del": "delete",
            "pgup": "page_up", "pgdn": "page_down", "hash": "#"}


def key_to_scan(name: str) -> tuple[int, bool, bool]:
    """Key name or character -> (scan code, extended, needs shift). Raises ValueError if unknown."""
    raw = name.strip() if name.strip() else name
    if len(raw) == 1:
        ch = raw
        if ch.isalpha() and ch.isupper():
            return (*_SC[ch.lower()], True)
        if ch in _SHIFTED:
            return (*_SC[_SHIFTED[ch]], True)
        if ch == " ":
            return (*_SC["space"], False)
        if ch in _SC:
            return (*_SC[ch], False)
        raise ValueError(f"Unknown key: {name!r}")
    low = _ALIASES.get(raw.lower(), raw.lower())
    if len(low) == 1:
        return key_to_scan(low)
    if low in _SC:
        return (*_SC[low], False)
    raise ValueError(f"Unknown key: {name!r}")


class SendInputBackend(InputBackend):
    name = "sendinput"

    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x8
    MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x1, 0x8000, 0x4000
    _BTN = {"left": (0x2, 0x4), "right": (0x8, 0x10), "middle": (0x20, 0x40)}

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("SendInput is Windows only")
        from ctypes import wintypes

        ulong_ptr = ctypes.c_size_t

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ulong_ptr)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ulong_ptr)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        self._INPUT, self._MI, self._KI, self._U = INPUT, MOUSEINPUT, KEYBDINPUT, _U
        self._user32 = ctypes.windll.user32
        self._user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]

    def _send(self, inp) -> None:
        self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(self._INPUT))

    def _mouse(self, flags: int, dx: int = 0, dy: int = 0) -> None:
        self._send(self._INPUT(type=0, u=self._U(mi=self._MI(dx, dy, 0, flags, 0, 0))))

    def _scan(self, scan: int, extended: bool, down: bool) -> None:
        flags = self.KEYEVENTF_SCANCODE | (self.KEYEVENTF_EXTENDEDKEY if extended else 0) | \
            (0 if down else self.KEYEVENTF_KEYUP)
        self._send(self._INPUT(type=1, u=self._U(ki=self._KI(0, scan, flags, 0, 0))))

    def move(self, x, y):
        u = self._user32
        # virtual desktop, so multi-monitor setups work; 0..65535 normalised coordinates
        vx, vy, vw, vh = u.GetSystemMetrics(76), u.GetSystemMetrics(77), u.GetSystemMetrics(78), u.GetSystemMetrics(79)
        nx = int(round((int(x) - vx) * 65535 / max(1, vw - 1)))
        ny = int(round((int(y) - vy) * 65535 / max(1, vh - 1)))
        self._mouse(self.MOUSEEVENTF_MOVE | self.MOUSEEVENTF_ABSOLUTE | self.MOUSEEVENTF_VIRTUALDESK, nx, ny)

    def button(self, down, button="left"):
        d, u = self._BTN.get(button, self._BTN["left"])
        self._mouse(d if down else u)

    def key(self, down, key):
        scan, ext, shift = key_to_scan(key)
        sh = _SC["shift_l"][0]
        if shift and down:
            self._scan(sh, False, True)
        self._scan(scan, ext, down)
        if shift and not down:
            self._scan(sh, False, False)

    def type_text(self, text, delay):
        for ch in text:
            try:
                self.key(True, ch)
                self.key(False, ch)
            except ValueError:
                continue  # characters with no key on a US layout are skipped
            if delay:
                time.sleep(delay)
