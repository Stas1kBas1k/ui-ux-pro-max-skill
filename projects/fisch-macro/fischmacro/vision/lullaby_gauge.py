"""Lullaby's metronome, as it really looks (player's recording, 40-63 s).

A half-moon above the reel: a ring split into lit (light) and dark parts, which change during the catch,
and a pendulum swinging across it from left to right. A click while the pendulum is over a lit part is a
hit (the bar turns green); elsewhere it is a miss (the bar turns red, -5% progress).

Read in polar coordinates around the moon's centre (the middle of the reel's top edge):

* the ring is the band of radii that is either very dark or very light all the way round;
* the ring itself does not move, so its look is the median of the last frames; lit parts = light there;
* the pendulum is where the ring differs most from that median right now.

The result is a ``TimingResult`` (pointer 0 = left end, 1 = right end; segments = lit parts), so the
existing timing solver (input-delay learning, prediction, one click per lit part) plays it unchanged.
"""
from __future__ import annotations

from collections import deque

import cv2
import numpy as np

from fischmacro.vision.minigames import TimingResult

ANGLES = 360  # rows of the half-plane unwrap (0.5 degree each)


class LullabyGauge:
    def __init__(self, history: int = 15):
        self.history = history
        self.offset: tuple[float, float] | None = None  # where the moon really is, relative to the estimate
        self.reset()

    def reset(self) -> None:
        self.radius: int | None = None
        self.ring_hist: deque[np.ndarray] = deque(maxlen=self.history)
        self.fan_hist: deque[np.ndarray] = deque(maxlen=self.history)
        self.misses = 0

    def _unwrap(self, img: np.ndarray, centre: tuple[float, float], rmax: int) -> np.ndarray:
        pol = cv2.warpPolar(img, (rmax, 2 * ANGLES), centre, rmax, cv2.WARP_POLAR_LINEAR)
        return pol[ANGLES:]  # angles 180..360 deg: left -> top -> right (image y points down)

    def _find_radius(self, gray: np.ndarray, rmin: int) -> int | None:
        r, score = self._ring(gray, rmin)
        return r if score >= 0.75 else None

    @staticmethod
    def _ring(gray: np.ndarray, rmin: int) -> tuple[int | None, float]:
        """The radius whose band is all very dark or very light (the ring), and how clean it is."""
        best, best_r = 0.0, None
        for r in range(rmin, gray.shape[1] - 4, 2):
            band = gray[:, r - 2:r + 3]
            dark, light = float((band < 55).mean()), float((band > 195).mean())
            share = dark + light
            if share > best and dark > 0.05 and light > 0.05:
                best, best_r = share, r
        return best_r, best

    def _locate(self, img: np.ndarray, centre: tuple[float, float], scale: float, rmax: int) -> None:
        """The estimate comes from the saved reel region, which can be a little off on another screen; a
        centre 25-50 px off bends the angles enough to click on the red part. Try positions around it and
        keep the one where the ring is sharpest (only exactly round about its true centre)."""
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        k = 2  # scored at half the radius samples and a quarter of the angles: ~10x cheaper, same peak
        rmin = int(0.07 * scale) // k
        n = ANGLES // 4

        def score(dx: float, dy: float, full: bool) -> float:
            if full:
                pol = cv2.warpPolar(g, (rmax, 2 * ANGLES), (centre[0] + dx, centre[1] + dy), rmax,
                                    cv2.WARP_POLAR_LINEAR)[ANGLES:]
                return self._ring(pol, rmin * k)[1]
            pol = cv2.warpPolar(g, (rmax // k, 2 * n), (centre[0] + dx, centre[1] + dy), rmax,
                                cv2.WARP_POLAR_LINEAR)[n:]
            return self._ring(pol, max(3, rmin))[1]

        best_d = (0.0, 0.0)
        # coarse (about +-50 px at 1080p), then finer, both cheap; then a last look at full resolution
        for step, span, full in ((0.012 * scale, 4, False), (0.004 * scale, 3, False), (0.002 * scale, 2, True)):
            cx, cy = best_d
            best = -1.0
            for i in range(-span, span + 1):
                for j in range(-span, span + 1):
                    d = (cx + i * step, cy + j * step)
                    sc = score(*d, full)
                    if sc > best + 1e-6:
                        best, best_d = sc, d
        # the real gauge scores ~0.97; ring-like shapes elsewhere (e.g. the test game) reach ~0.78
        if best >= 0.9:
            self.offset = best_d

    def update(self, img: np.ndarray, centre: tuple[float, float], scale: float) -> TimingResult:
        """``img``: the frame (or a crop holding the gauge); ``centre``: the moon's centre in it (pixels);
        ``scale``: the game's height in pixels (sizes follow it)."""
        res = TimingResult()
        rmax = int(0.24 * scale)
        if img is None or img.size == 0 or rmax < 40:
            return res
        if self.radius is None and self.offset is None:
            self._tries = getattr(self, "_tries", 0) + 1
            if self._tries % 30 != 1:  # not on screen yet: look again about once a second, not every frame
                return res
            self._locate(img, centre, scale, rmax)
        if self.offset is not None:
            centre = (centre[0] + self.offset[0], centre[1] + self.offset[1])
        gray = cv2.cvtColor(self._unwrap(img, centre, rmax), cv2.COLOR_BGR2GRAY)
        if self.radius is None:
            self.radius = self._find_radius(gray, int(0.07 * scale))
            if self.radius is None:
                return res
        r = self.radius
        ring = gray[:, r - 3:r + 4].mean(axis=1)
        # still a gauge here? a ring is mostly very dark or very light
        if float(((ring < 70) | (ring > 180)).mean()) < 0.6:
            self.misses += 1
            if self.misses > 10:
                self.reset()
            return res
        self.misses = 0
        self.ring_hist.append(ring)
        # the pendulum is the one long moving thing: compare the whole fan (centre to past the ring) with its
        # median over the last frames, where the pendulum is somewhere else each time
        fan = gray[:, int(0.25 * r):min(gray.shape[1], int(1.3 * r))].astype(np.float32)
        self.fan_hist.append(fan)
        if len(self.ring_hist) < 4:
            return res
        static = np.median(np.stack(self.ring_hist), axis=0)
        lit = static > 150
        still = np.median(np.stack(self.fan_hist), axis=0)
        change = (np.abs(fan - still) > 40).mean(axis=1)   # per angle: share of the radius that changed
        change = np.convolve(change, np.ones(11) / 11, mode="same")
        a = int(change.argmax())
        if change[a] < 0.25:
            return res
        res.present, res.source = True, "gauge"
        res.pointer = a / (ANGLES - 1)
        res.segments = _runs_of(lit)
        res.confidence = float(min(1.0, change[a] / 0.5))
        return res


def _runs_of(mask: np.ndarray) -> list[tuple[float, float]]:
    out, start = [], None
    n = len(mask)
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= 6:
                out.append((start / (n - 1), (i - 1) / (n - 1)))
            start = None
    if start is not None and n - start >= 6:
        out.append((start / (n - 1), 1.0))
    return out
