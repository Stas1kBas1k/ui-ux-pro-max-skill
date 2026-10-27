"""Detectors for rod-specific minigames that run on top of the reel.

* Timing (Lullaby): a pointer swings along a track; some track sections are lit.
* Symbol match (Stellarwave Melody): a target sign is shown; the matching sign
  among several options must be clicked.
* Targets (Halibut Harpoon style): marked spots to click.

All are colour/shape based and configured per profile, so they can be retuned
from the calibration tool without code changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from fischmacro.vision.frame import Frame, color_mask


def _runs(mask: np.ndarray, max_gap: int = 1) -> list[tuple[int, int]]:
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    splits = np.flatnonzero(np.diff(idx) > max_gap + 1)
    starts = np.concatenate(([idx[0]], idx[splits + 1]))
    ends = np.concatenate((idx[splits], [idx[-1]])) + 1
    return list(zip(starts.tolist(), ends.tolist()))


@dataclass
class TimingResult:
    present: bool = False
    pointer: float = 0.0                       # normalised to the track region
    segments: list[tuple[float, float]] = field(default_factory=list)
    confidence: float = 0.0

    def inside(self, x: float, margin: float = 0.0) -> bool:
        return any(a + margin <= x <= b - margin for a, b in self.segments)


def detect_timing(crop: np.ndarray | None, pointer_color: str, pointer_tol: int, lit_color: str, lit_tol: int,
                  axis: str = "horizontal") -> TimingResult:
    if crop is None or crop.size == 0:
        return TimingResult()
    if axis == "vertical":
        crop = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
    h, w = crop.shape[:2]
    pm = color_mask(crop, pointer_color, pointer_tol)
    lm = color_mask(crop, lit_color, lit_tol)
    pcols = pm.sum(axis=0) / (255.0 * h)
    lcols = lm.sum(axis=0) / (255.0 * h)
    res = TimingResult()
    pruns = [r for r in _runs(pcols >= 0.3) if (r[1] - r[0]) <= max(3, 0.08 * w)]
    if pruns:
        best = max(pruns, key=lambda r: float(pcols[r[0]:r[1]].sum()))
        weights = pcols[best[0]:best[1]]
        res.pointer = float(np.average(np.arange(best[0], best[1]), weights=weights) + 0.5) / w
        res.present = True
        res.confidence = float(min(1.0, weights.max() / 0.6))
    # The pointer is drawn over the track and hides part of a lit section: bridge that gap.
    lit = lcols >= 0.3
    gap = max(2, int(0.02 * w), (best[1] - best[0] + 2) if pruns else 0)
    res.segments = [(a / w, b / w) for a, b in _runs(lit, max_gap=gap) if b - a >= 0.02 * w]
    if not res.segments:
        res.confidence *= 0.5
    return res


def detect_timing_auto(crop: np.ndarray | None, axis: str = "horizontal") -> TimingResult:
    """Colour-free Lullaby reading for any rod skin: the pendulum is the thin line that stands out,
    lit sections are the stretches clearly brighter than the rest of the track."""
    from fischmacro.vision.detectors import shape_fish
    if crop is None or crop.size == 0:
        return TimingResult()
    if axis == "vertical":
        crop = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
    h, w = crop.shape[:2]
    res = TimingResult()
    found = shape_fish(crop, (2, w - 2))
    if found is None or found[1] < 0.5:
        return res
    px, conf, pw = found
    res.pointer, res.present, res.confidence = px, True, conf
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    y0, y1 = int(h * 0.2), max(int(h * 0.2) + 1, int(h * 0.8))
    v = hsv[y0:y1, :, 2].astype(np.float32).mean(axis=0)
    sat = hsv[y0:y1, :, 1].astype(np.float32).mean(axis=0)
    score = v + 0.5 * sat
    c = int(px * w)
    pad = max(2, pw + 1)
    score[max(0, c - pad):c + pad + 1] = np.nan
    base = float(np.nanmedian(score))
    lit = np.nan_to_num(score, nan=-1) > base + 35
    # bridge the pendulum: it hides part of a lit section
    if c - pad - 1 >= 0 and c + pad + 1 < w and lit[c - pad - 1] and lit[c + pad + 1]:
        lit[max(0, c - pad):c + pad + 1] = True
    res.segments = [(a / w, b / w) for a, b in _runs(lit, max_gap=max(2, int(0.02 * w))) if b - a >= 0.02 * w]
    if not res.segments:
        res.confidence *= 0.5
    return res


@dataclass
class MatchOption:
    x: float          # centre, client-normalised
    y: float
    score: float


@dataclass
class MatchResult:
    target_present: bool = False
    options: list[MatchOption] = field(default_factory=list)
    signature: int = 0     # changes when a new target sign is shown

    @property
    def best(self) -> MatchOption | None:
        return max(self.options, key=lambda o: o.score) if self.options else None


def _shape(mask: np.ndarray) -> np.ndarray | None:
    ys, xs = np.nonzero(mask)
    if xs.size < 6:
        return None
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return cv2.resize(crop, (32, 32), interpolation=cv2.INTER_AREA) > 96


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter) / union if union else 0.0


def detect_match(frame: Frame, target_region, options_region, symbol_color: str, tol: int,
                 min_area: float = 0.002) -> MatchResult:
    res = MatchResult()
    t_crop = frame.crop(target_region)
    o_crop = frame.crop(options_region)
    if t_crop is None or o_crop is None:
        return res
    target = _shape(color_mask(t_crop, symbol_color, tol))
    if target is None:
        return res
    res.target_present = True
    res.signature = int(np.packbits(target[::4, ::4]).sum()) * 131 + int(target.sum())
    cw, ch = frame.client_size
    ox, oy, ow, oh = options_region.to_rect(cw, ch)
    mask = color_mask(o_crop, symbol_color, tol)
    k = max(3, int(min(o_crop.shape[:2]) * 0.02) | 1)
    grouped = cv2.dilate(mask, np.ones((k, k), np.uint8))  # join strokes of one symbol
    n, labels, stats, _ = cv2.connectedComponentsWithStats(grouped, connectivity=8)
    area_total = float(mask.shape[0] * mask.shape[1])
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area / area_total < min_area:
            continue
        sym = _shape(np.where(labels[y:y + h, x:x + w] == i, mask[y:y + h, x:x + w], 0))
        if sym is None:
            continue
        res.options.append(MatchOption((ox + x + w / 2) / cw, (oy + y + h / 2) / ch, _iou(sym, target)))
    return res


@dataclass
class TargetsResult:
    targets: list[tuple[float, float]] = field(default_factory=list)  # client-normalised centres


def detect_targets(frame: Frame, region, color: str, tol: int, min_area: float = 0.0005,
                   max_area: float = 0.05) -> TargetsResult:
    crop = frame.crop(region)
    if crop is None:
        return TargetsResult()
    cw, ch = frame.client_size
    rx, ry, _, _ = region.to_rect(cw, ch)
    mask = cv2.morphologyEx(color_mask(crop, color, tol), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    total = float(mask.shape[0] * mask.shape[1])
    out = TargetsResult()
    for i in range(1, n):
        if min_area <= stats[i][4] / total <= max_area:
            cx, cy = cents[i]
            out.targets.append(((rx + cx) / cw, (ry + cy) / ch))
    return out
