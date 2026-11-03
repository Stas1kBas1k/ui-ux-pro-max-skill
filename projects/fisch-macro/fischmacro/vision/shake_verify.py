"""Only click shake candidates that actually say SHAKE.

The shape check finds "a short light word on a dark patch", which also matches player names in the
Roblox player list and similar UI (checked on the player's recording: 297 of 634 frames). A wrong click
while the line is out reels the line back in, so each new candidate is read once with OCR on a
background thread; the answer is remembered by position, so static UI is read once and then ignored.
Until a candidate is confirmed it is not clicked (the real button stays until it is clicked).
"""
from __future__ import annotations

import threading
import time

from fischmacro.vision.ocr import fuzzy_contains

CELL = 0.03          # positions closer than this (fraction of the window) share a verdict
REMEMBER_S = 20.0    # how long a verdict is kept


class ShakeVerifier:
    def __init__(self, ocr=None):
        self._ocr = ocr
        self._lock = threading.Lock()
        self._verdict: dict[tuple[int, int], tuple[bool, float, str]] = {}
        self._queue: list[tuple[tuple[int, int], object]] = []
        self._busy = False
        self.reads = 0
        self.last_text = ""

    @staticmethod
    def _key(t) -> tuple[int, int]:
        return round(t.x / CELL), round(t.y / CELL)

    def _engine(self):
        if self._ocr is None:
            from fischmacro.vision.ocr import OcrEngine
            self._ocr = OcrEngine.shared()
        return self._ocr

    def available(self) -> bool:
        return self._engine().available

    def filter(self, image, targets, client_size, now: float | None = None, origin=(0, 0)):
        """Targets confirmed as SHAKE. Unknown ones are queued for reading and left out for now."""
        if not targets:
            return []
        if not self.available():
            return targets  # no OCR installed: fall back to the shape check alone
        now = time.perf_counter() if now is None else now
        out = []
        W, H = client_size
        with self._lock:
            for t in targets:
                k = self._key(t)
                v = self._verdict.get(k)
                if v is not None and now - v[1] < REMEMBER_S:
                    if v[0]:
                        out.append(t)
                    continue
                if any(q[0] == k for q in self._queue):
                    continue
                x0, x1 = int((t.x - t.w / 2) * W) - origin[0], int((t.x + t.w / 2) * W) - origin[0]
                y0, y1 = int((t.y - t.h / 2) * H) - origin[1], int((t.y + t.h / 2) * H) - origin[1]
                crop = image[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
                if crop.size:
                    self._queue.append((k, crop.copy()))
            start = bool(self._queue) and not self._busy
            if start:
                self._busy = True
        if start:
            threading.Thread(target=self._run, name="shake-ocr", daemon=True).start()
        return out

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._busy = False
                    return
                k, crop = self._queue.pop(0)
            try:
                text = self._engine().text(crop)
            except Exception:  # noqa: BLE001 - unreadable counts as "not a shake button"
                text = ""
            ok = fuzzy_contains(text, "shake")
            with self._lock:
                self.reads += 1
                self.last_text = text
                self._verdict[k] = (ok, time.perf_counter(), text)

    def wait_idle(self, timeout: float = 5.0) -> None:
        """For tests: block until queued candidates have been read."""
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            with self._lock:
                if not self._busy and not self._queue:
                    return
            time.sleep(0.01)
