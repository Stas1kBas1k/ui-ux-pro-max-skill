"""Colour-free reel tracking, so every rod skin works without calibration.

The track is whatever look most columns of the reel region share. Decorations at the ends of skinned
frames look different, so they fall outside the track. Inside the track, the fish is the thin line that
stands out (detectors.shape_fish) and the catch bar is the stretch that differs from the empty track.
"""
from __future__ import annotations

import cv2
import numpy as np

from fischmacro.vision.detectors import ReelResult, _runs, shape_fish

ROWS = 10  # the region is squeezed to this many rows: enough for gradients, cheap to compare


def _profile(crop: np.ndarray) -> np.ndarray:
    h, w = crop.shape[:2]
    y0, y1 = int(h * 0.15), max(int(h * 0.15) + 1, int(h * 0.85))  # outer rows hold frame outlines
    return cv2.resize(crop[y0:y1], (w, ROWS), interpolation=cv2.INTER_AREA).astype(np.int16)


def _distance(prof: np.ndarray, sig: np.ndarray) -> np.ndarray:
    """Per column: how different it looks from a signature (ROWS x 3), 0..255."""
    return np.abs(prof - sig[:, None, :]).max(axis=2).mean(axis=0)


def _modal_signature(prof: np.ndarray, diff: float) -> np.ndarray:
    """The column look shared by the most columns (the empty track, as the bar and decorations are smaller)."""
    w = prof.shape[1]
    idx = np.arange(int(w * 0.03), int(w * 0.97), max(1, w // 120))
    cols = prof[:, idx].transpose(1, 0, 2).reshape(len(idx), -1)
    d = np.abs(cols[:, None, :] - cols[None, :, :]).reshape(len(idx), len(idx), ROWS, 3).max(axis=3).mean(axis=2)
    best = int((d <= diff).sum(axis=1).argmax())
    members = d[best] <= diff
    return np.median(prof[:, idx[members]], axis=1)


class AdaptiveReel:
    """Stateful: call ``update`` every frame with the reel crop. ``reset`` when the rod or skin changes."""

    DIFF = 24          # mean per-column difference that counts as "not the empty track"
    MIN_BAR = 0.04     # narrowest bar, as a fraction of the region

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.track_sig: np.ndarray | None = None
        self.extent: tuple[int, int] | None = None
        self.shape: tuple[int, int] | None = None
        self.last_bar: tuple[float, float] | None = None
        self.hits = 0
        self.misses = 0

    def _track_extent(self, match: np.ndarray, w: int) -> tuple[int, int] | None:
        runs = [r for r in _runs(match, max_gap=max(2, int(0.01 * w))) if r[1] - r[0] >= 0.03 * w]
        if not runs:
            return None
        lo, hi = runs[0][0], runs[-1][1]
        if self.extent:
            lo, hi = min(lo, self.extent[0]), max(hi, self.extent[1])
        return lo, hi

    def update(self, crop: np.ndarray | None) -> ReelResult:
        res = ReelResult()
        if crop is None or crop.size == 0 or crop.shape[1] < 40:
            return res
        h, w = crop.shape[:2]
        if self.shape != (h, w):
            self.reset()
            self.shape = (h, w)
        prof = _profile(crop)
        sig = self.track_sig if self.track_sig is not None else _modal_signature(prof, self.DIFF)
        dist = _distance(prof, sig)
        match = dist <= self.DIFF
        if match.mean() < 0.25:
            # nothing here looks like the remembered track: a new skin, or no minigame at all
            self.misses += 1
            if self.misses > 20:
                self.reset()
                self.shape = (h, w)
            return res
        extent = self._track_extent(match, w)
        if extent is None or extent[1] - extent[0] < 0.3 * w:
            return res
        lo, hi = extent
        pad = int(0.02 * w)
        fish = shape_fish(crop, (lo + pad, hi - pad))  # the track's end caps are lines too
        if fish is None or fish[1] < 0.5:
            return res
        fx, fconf, fwid = fish
        c = int(fx * w)
        res.fish_found, res.fish_x, res.fish_confidence = True, fx, fconf
        res.ui_present = True
        self.misses = 0

        diff = ~match
        diff[:lo] = False
        diff[hi:] = False
        fpad = max(2, fwid)
        f0, f1 = max(lo, c - fpad), min(hi, c + fpad + 1)
        # the fish is drawn over the bar: bridge it so it neither splits the bar nor counts as bar
        left_in = diff[max(lo, f0 - 2)] if f0 - 2 >= lo else False
        right_in = diff[min(hi - 1, f1 + 1)] if f1 + 1 < hi else False
        diff[f0:f1] = left_in and right_in
        if left_in != right_in:
            diff[f0:f1] = True if (left_in or right_in) and fwid < 0.02 * w else False

        runs = [r for r in _runs(diff, max_gap=max(2, int(0.012 * w))) if r[1] - r[0] >= self.MIN_BAR * w]
        if not runs:
            return res
        if self.last_bar is not None:
            lc = (self.last_bar[0] + self.last_bar[1]) / 2 * w
            b0, b1 = min(runs, key=lambda r: abs((r[0] + r[1]) / 2 - lc) - 0.25 * (r[1] - r[0]))
        else:
            b0, b1 = max(runs, key=lambda r: r[1] - r[0])
        if (b1 - b0) > 0.97 * (hi - lo):
            return res
        res.bar_found = True
        res.bar_left, res.bar_right = b0 / w, b1 / w
        res.bar_confidence = 0.95 if self.hits >= 3 else 0.75
        self.hits += 1
        self.last_bar = (res.bar_left, res.bar_right)
        self.extent = extent
        # learn the empty track's look from the columns that are neither bar nor fish
        empty = match.copy()
        empty[:lo] = False
        empty[hi:] = False
        empty[max(0, b0 - 3):min(w, b1 + 3)] = False
        empty[max(0, f0 - 3):min(w, f1 + 3)] = False
        if empty.sum() >= 0.1 * w:
            new = np.median(prof[:, empty], axis=1)
            self.track_sig = new if self.track_sig is None else 0.85 * self.track_sig + 0.15 * new
        return res
