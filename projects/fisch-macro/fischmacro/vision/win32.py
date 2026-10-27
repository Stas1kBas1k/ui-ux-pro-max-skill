"""Minimal Win32 helpers via ctypes: DPI awareness and locating the Roblox window.

Only public, read-only window APIs are used (window title, client rectangle,
foreground window). Nothing touches the game process itself.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == "win32"


@dataclass
class WindowInfo:
    found: bool = False
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    focused: bool = False
    minimized: bool = False
    title: str = ""
    handle: int = 0


def enable_dpi_awareness() -> None:
    """Make capture and input coordinates physical pixels under any DPI scaling."""
    if not IS_WINDOWS:
        return
    import ctypes
    try:
        # PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:  # noqa: BLE001 - fall back to older APIs
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not enable DPI awareness: %s", exc)


def find_window(title: str) -> WindowInfo:
    """Find a visible top-level window whose title equals ``title`` (case-insensitive)."""
    if not IS_WINDOWS:
        return WindowInfo()
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    wanted = title.strip().lower()
    matches: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value.strip().lower() == wanted:
            matches.append(hwnd)
        return True

    user32.EnumWindows(_enum, 0)
    if not matches:
        return WindowInfo()
    hwnd = matches[0]
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return WindowInfo(
        found=True, left=pt.x, top=pt.y,
        width=rect.right - rect.left, height=rect.bottom - rect.top,
        focused=user32.GetForegroundWindow() == hwnd,
        minimized=bool(user32.IsIconic(hwnd)),
        title=title, handle=int(hwnd),
    )


def focus_window(handle: int) -> bool:
    """Bring a window to the front (what clicking its title bar does). Returns True if it is focused."""
    if not IS_WINDOWS or not handle:
        return False
    import ctypes
    user32 = ctypes.windll.user32
    try:
        if user32.IsIconic(handle):
            user32.ShowWindow(handle, 9)  # SW_RESTORE
        # Windows only lets the foreground app hand focus over; a dummy Alt tap lifts that lock.
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(handle)
        return user32.GetForegroundWindow() == handle
    except Exception as exc:  # noqa: BLE001
        log.debug("focus_window failed: %s", exc)
        return False
