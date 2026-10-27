"""Capture sources. All of them produce :class:`Frame` objects of the game client area."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from fischmacro.vision.frame import Frame
from fischmacro.vision.win32 import IS_WINDOWS, WindowInfo, find_window

log = logging.getLogger(__name__)


class CaptureError(Exception):
    pass


class CaptureSource:
    """Base class. ``rect`` is (x, y, w, h) inside the client area, or None for all of it."""

    simulated = False

    def locate(self) -> WindowInfo:
        raise NotImplementedError

    def grab(self, win: WindowInfo, rect: tuple[int, int, int, int] | None = None) -> Frame:
        raise NotImplementedError

    def close(self) -> None:
        pass


class ScreenCapture(CaptureSource):
    """MSS-based capture of either the Roblox window or a whole monitor.

    MSS handles are not thread-safe, so one is created lazily per thread.
    """

    def __init__(self, mode: str = "window", window_title: str = "Roblox", monitor: int = 1):
        self.mode = mode
        self.window_title = window_title
        self.monitor = monitor
        self._local = threading.local()
        self._win_cache: tuple[float, WindowInfo] | None = None

    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            try:
                import mss
                sct = mss.mss()
            except Exception as exc:  # noqa: BLE001
                raise CaptureError(f"Screen capture unavailable: {exc}") from exc
            self._local.sct = sct
        return sct

    def locate(self) -> WindowInfo:
        if self.mode == "window":
            now = time.monotonic()
            if self._win_cache and now - self._win_cache[0] < 0.5:
                return self._win_cache[1]
            if not IS_WINDOWS:
                info = WindowInfo()
            else:
                info = find_window(self.window_title)
            self._win_cache = (now, info)
            return info
        monitors = self._sct().monitors
        idx = self.monitor if 0 < self.monitor < len(monitors) else 1
        m = monitors[idx] if len(monitors) > idx else monitors[0]
        return WindowInfo(True, m["left"], m["top"], m["width"], m["height"], focused=True, title=f"Monitor {idx}")

    def grab(self, win: WindowInfo, rect=None) -> Frame:
        if not win.found or win.width <= 0 or win.height <= 0:
            raise CaptureError("Game window not found")
        if win.minimized:
            raise CaptureError("Game window is minimised")
        x, y, w, h = rect if rect else (0, 0, win.width, win.height)
        box = {"left": win.left + x, "top": win.top + y, "width": max(1, w), "height": max(1, h)}
        try:
            shot = self._sct().grab(box)
        except Exception as exc:  # noqa: BLE001
            self._local.sct = None
            raise CaptureError(f"Capture failed: {exc}") from exc
        img = np.asarray(shot)[:, :, :3]  # BGRA -> BGR view
        return Frame(np.ascontiguousarray(img), (win.width, win.height), (x, y), (win.left, win.top),
                     time.monotonic(), full=rect is None,
                     meta={"window_found": True, "window_focused": win.focused})

    def close(self) -> None:
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            try:
                sct.close()
            except Exception:  # noqa: BLE001
                pass


class SimulationCapture(CaptureSource):
    """Captures frames from the built-in simulated game (test mode, no real input)."""

    simulated = True

    def __init__(self, game):
        self.game = game

    def locate(self) -> WindowInfo:
        return WindowInfo(True, 0, 0, self.game.width, self.game.height, focused=True, title="Simulation")

    def grab(self, win: WindowInfo, rect=None) -> Frame:
        self.game.advance_realtime()
        img = self.game.render()
        x, y, w, h = rect if rect else (0, 0, self.game.width, self.game.height)
        crop = img[y:y + h, x:x + w].copy()
        return Frame(crop, (self.game.width, self.game.height), (x, y), (0, 0), time.monotonic(),
                     full=rect is None, meta={"window_found": True, "window_focused": True})


class ImageFolderCapture(CaptureSource):
    """Replays saved screenshots (PNG/JPG) in a loop. Useful for offline calibration."""

    simulated = True

    def __init__(self, folder: Path, interval: float = 1.0):
        self.files = sorted([p for p in Path(folder).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp")])
        if not self.files:
            raise CaptureError(f"No images in {folder}")
        self.interval = interval
        self._start = time.monotonic()
        self._cache: dict[Path, np.ndarray] = {}

    def _current(self) -> np.ndarray:
        idx = int((time.monotonic() - self._start) / self.interval) % len(self.files)
        p = self.files[idx]
        if p not in self._cache:
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is None:
                raise CaptureError(f"Cannot read {p}")
            self._cache[p] = img
        return self._cache[p]

    def locate(self) -> WindowInfo:
        h, w = self._current().shape[:2]
        return WindowInfo(True, 0, 0, w, h, focused=True, title="Screenshots")

    def grab(self, win: WindowInfo, rect=None) -> Frame:
        img = self._current()
        h, w = img.shape[:2]
        x, y, rw, rh = rect if rect else (0, 0, w, h)
        return Frame(img[y:y + rh, x:x + rw].copy(), (w, h), (x, y), (0, 0), time.monotonic(),
                     full=rect is None, meta={"window_found": True, "window_focused": True})
