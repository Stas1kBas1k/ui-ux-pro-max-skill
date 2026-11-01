"""Objects that fall onto the catch bar: Pinion's Aria's notes, Santa's Miracle Rod's presents, Starshell Rod's
shells (Fisch wiki: "Notes will start falling across the bar", "Catching the Falling Presents with the fishing
bar will grant +10% Progress", "Shells fall every 4 seconds").

The wiki says what falls and that the bar has to catch it, not what it looks like, so nothing here depends on a
colour or a shape: the band above the reel is compared with its own recent median (the still background), and
whatever moves *down* toward the track from clearly above it is a falling object. The fish line is ignored - it
moves sideways and sits on the track. Positions are fractions of the reel region; ``eta`` is the time to land.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

BAND = 4.0   # how far above the track to look, in track heights
WIDTH = 320  # the band is scaled to this width (speed, and the same thresholds at every resolution)


@dataclass
class Drop:
    x: float          # across the reel (0 = left end, 1 = right end)
    y: float          # 0 = top of the band, 1 = the top of the track
    vy: float = 0.0   # band heights per second (positive = falling)
    seen: int = 1     # frames it has been followed

    @property
    def eta(self) -> float | None:
        return (1.0 - self.y) / self.vy if self.vy > 0.05 else None


class FallingObjects:
    def __init__(self, history: int = 9):
        self.hist: deque[np.ndarray] = deque(maxlen=history)
        self.drops: list[Drop] = []
        self._t: float | None = None

    def reset(self) -> None:
        self.hist.clear()
        self.drops = []
        self._t = None

    @staticmethod
    def band_region(reel):
        """The area above the reel plus the reel's top third (a Region of the same kind as ``reel``)."""
        top = max(0.0, reel.y - BAND * reel.h)
        return type(reel)(reel.x, top, reel.w, reel.y - top + reel.h / 3)

    @staticmethod
    def band(crop: np.ndarray | None) -> np.ndarray | None:
        """The band crop, scaled to WIDTH, in grey."""
        if crop is None or crop.size == 0 or crop.shape[0] < 8 or crop.shape[1] < 20:
            return None
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        hh = max(8, int(round(g.shape[0] * WIDTH / g.shape[1])))
        return cv2.resize(g, (WIDTH, hh), interpolation=cv2.INTER_AREA)

    def update(self, crop: np.ndarray | None, now: float) -> list[Drop]:
        """``crop``: the frame cut to ``band_region(reel)``."""
        g = self.band(crop)
        dt = 0.0 if self._t is None else max(1e-3, now - self._t)
        self._t = now
        if g is None:
            return []
        if self.hist and self.hist[-1].shape != g.shape:
            self.reset()
        self.hist.append(g)
        if len(self.hist) < 4:
            return []
        still = np.median(np.stack(self.hist), axis=0).astype(np.int16)
        moving = (np.abs(g.astype(np.int16) - still) > 38).astype(np.uint8)
        moving = cv2.morphologyEx(moving, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        hb = g.shape[0]
        track_top = hb - max(1, int(hb / (BAND + 1 / 3) / 3))  # rows below this are the track itself
        n, _, stats, cents = cv2.connectedComponentsWithStats(moving, connectivity=8)
        found = []
        for i in range(1, n):
            x0, y0, ww, hh, area = stats[i]
            if area < 6 or ww > 0.12 * WIDTH or hh > 0.6 * hb:
                continue  # noise, or something wide (a slash, a flash) - not an object
            cx, cy = cents[i]
            if cy > track_top - 2:
                continue  # on the track: the fish line or the bar
            found.append(Drop(float(cx / WIDTH), float(cy / track_top)))
        # follow each object from the last frame: same column, a little lower
        out = []
        for d in found:
            prev = min(self.drops, key=lambda p: abs(p.x - d.x) + abs(p.y - d.y), default=None)
            if prev is not None and abs(prev.x - d.x) < 0.04 and -0.05 <= d.y - prev.y < 0.6 and dt > 0:
                v = (d.y - prev.y) / dt
                d.vy = v if prev.seen == 1 else 0.5 * prev.vy + 0.5 * v
                d.seen = prev.seen + 1
            out.append(d)
        self.drops = out
        return [d for d in out if d.seen >= 2 and d.vy > 0.05]


def catch_aim(fish: float, bar_l: float, bar_r: float, drops: list[Drop], margin: float = 0.06,
              horizon: float = 1.0) -> float:
    """Where to aim the bar's centre: on the fish, unless a falling object will land within ``horizon`` seconds
    and the bar can be under it while the fish stays inside (with a margin). The fish always wins: losing it
    costs more than a missed object."""
    width = max(1e-3, bar_r - bar_l)
    half = width / 2
    soon = sorted((d for d in drops if d.eta is not None and d.eta <= horizon), key=lambda d: d.eta)
    for d in soon:
        lo = max(fish - half + margin * width, d.x - half + 0.1 * width)
        hi = min(fish + half - margin * width, d.x + half - 0.1 * width)
        if lo <= hi:
            return min(max(fish, lo), hi)  # the centre closest to the fish that also covers the object
    return fish
