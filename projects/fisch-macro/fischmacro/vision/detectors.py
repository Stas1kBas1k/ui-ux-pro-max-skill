"""Game-element detectors.

Each detector works on a single calibrated region and returns a small result
dataclass with a confidence in [0, 1]. Detectors are pure functions of the
image and configuration, which keeps them easy to test with saved screenshots.

Coordinates inside the reel/progress/cast results are normalised to their own
region (0 = left/top edge, 1 = right/bottom edge). Shake targets are normalised
to the whole game client area so they can be clicked directly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from fischmacro.profiles.schema import DetectionConfig, Region
from fischmacro.vision.frame import Frame, color_mask

log = logging.getLogger(__name__)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def _runs(mask: np.ndarray, max_gap: int = 0) -> list[tuple[int, int]]:
    """Contiguous True runs of a 1-D boolean array as (start, end_exclusive), bridging gaps <= max_gap."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    splits = np.flatnonzero(np.diff(idx) > max_gap + 1)
    starts = np.concatenate(([idx[0]], idx[splits + 1]))
    ends = np.concatenate((idx[splits], [idx[-1]])) + 1
    return list(zip(starts.tolist(), ends.tolist()))


# --------------------------------------------------------------------------- reel minigame

@dataclass
class ReelResult:
    ui_present: bool = False      # the catch bar is visible
    fish_found: bool = False
    fish_x: float = 0.0           # normalised to the reel region
    bar_left: float = 0.0
    bar_right: float = 0.0
    fish_confidence: float = 0.0
    bar_confidence: float = 0.0
    bar_found: bool = False       # False with ui_present = fish seen on the track but the bar was not

    @property
    def present(self) -> bool:
        return self.ui_present and self.fish_found

    @property
    def confidence(self) -> float:
        return min(self.fish_confidence, self.bar_confidence) if self.present else self.bar_confidence * 0.5

    @property
    def bar_center(self) -> float:
        return (self.bar_left + self.bar_right) / 2

    @property
    def bar_width(self) -> float:
        return self.bar_right - self.bar_left


def detect_reel(crop: np.ndarray | None, cfg: DetectionConfig) -> ReelResult:
    if crop is None or crop.size == 0:
        return ReelResult()
    h, w = crop.shape[:2]
    res = ReelResult()

    fish = color_mask(crop, cfg.fish_color, cfg.fish_tolerance)
    fish_fill = fish.sum(axis=0, dtype=np.float32) / (255.0 * h)
    fish_cols = fish_fill >= 0.2
    fish_runs = _runs(fish_cols, max_gap=1)
    if fish_runs:
        # The fish is the strongest compact cluster; wide clusters are background noise.
        best = max(fish_runs, key=lambda r: float(fish_fill[r[0]:r[1]].sum()) / max(1.0, (r[1] - r[0]) ** 0.25))
        width = best[1] - best[0]
        if width <= max(4, 0.25 * w):
            weights = fish_fill[best[0]:best[1]]
            cx = float(np.average(np.arange(best[0], best[1]), weights=weights)) + 0.5
            res.fish_found = True
            res.fish_x = cx / w
            res.fish_confidence = _clamp(float(weights.max()) / 0.55) * _clamp(width / 2.0)

    bar = color_mask(crop, cfg.bar_color, cfg.bar_tolerance)
    if getattr(cfg, "bar_tolerance2", 0) > 0:
        bar = cv2.bitwise_or(bar, color_mask(crop, cfg.bar_color2, cfg.bar_tolerance2))
    bar_fill = bar.sum(axis=0, dtype=np.float32) / (255.0 * h)
    bar_cols = bar_fill >= cfg.bar_column_fill
    if res.fish_found:
        # The fish icon is drawn over the bar; treat its columns as bar to avoid a split.
        bar_cols = bar_cols | fish_cols
    max_gap = max(2, int(0.03 * w))
    candidates = [r for r in _runs(bar_cols, max_gap=max_gap) if (r[1] - r[0]) >= cfg.bar_min_width * w]
    if candidates:
        best = max(candidates, key=lambda r: float(bar_fill[r[0]:r[1]].sum()))
        width = best[1] - best[0]
        coverage = float(bar_fill[best[0]:best[1]].mean())
        if width < 0.97 * w:  # a fully white region is not a catch bar
            res.ui_present = True
            res.bar_left = best[0] / w
            res.bar_right = best[1] / w
            res.bar_confidence = _clamp(coverage / 0.75)
            res.bar_found = True
    if not res.ui_present and res.fish_found and res.fish_confidence >= 0.5 and \
            float(bar_fill.sum()) >= 0.03 * w:
        # Fish on the track and bar-coloured pixels nearby, but no clean bar run (blurred,
        # half-transparent or recoloured bar). Still a minigame: the FSM steers on the fish alone.
        res.ui_present = True
    return res


# --------------------------------------------------------------------------- progress / cast

@dataclass
class FillResult:
    present: bool = False
    fill: float = 0.0
    confidence: float = 0.0


def detect_progress(crop: np.ndarray | None, cfg: DetectionConfig) -> FillResult:
    if crop is None or crop.size == 0:
        return FillResult()
    h, w = crop.shape[:2]
    mask = color_mask(crop, cfg.progress_color, cfg.progress_tolerance)
    cols = mask.sum(axis=0, dtype=np.float32) / (255.0 * h) >= 0.4
    filled = int(cols.sum())
    runs = _runs(cols, max_gap=max(1, int(0.02 * w)))
    if runs and runs[0][0] <= 0.1 * w:
        fill = runs[0][1] / w
        consistency = filled / max(1, runs[0][1] - runs[0][0])
        return FillResult(True, _clamp(fill), _clamp(consistency))
    return FillResult(False, filled / w, 0.3 if filled else 0.0)


def detect_cast(crop: np.ndarray | None, cfg: DetectionConfig) -> FillResult:
    if crop is None or crop.size == 0:
        return FillResult()
    mask = color_mask(crop, cfg.cast_color, cfg.cast_tolerance)
    if cfg.cast_orientation == "horizontal":
        frac = mask.sum(axis=0, dtype=np.float32) / (255.0 * mask.shape[0])
        lines = frac >= 0.35
        runs = _runs(lines, max_gap=2)
        if not runs:
            return FillResult()
        start, end = runs[0]
        fill = end / len(lines)
    else:
        frac = mask.sum(axis=1, dtype=np.float32) / (255.0 * mask.shape[1])
        lines = frac >= 0.35
        runs = _runs(lines, max_gap=2)
        if not runs:
            return FillResult()
        start, end = runs[-1]  # fills from the bottom
        fill = (len(lines) - start) / len(lines)
    span = end - start
    if span < 2:
        return FillResult()
    consistency = float(lines[start:end].mean())
    return FillResult(True, _clamp(fill), _clamp(consistency * min(1.0, span / 4)))


# --------------------------------------------------------------------------- shake prompts

@dataclass
class Target:
    x: float          # centre, normalised to client area
    y: float
    w: float
    h: float
    confidence: float


@dataclass
class ShakeResult:
    targets: list[Target] = field(default_factory=list)

    @property
    def present(self) -> bool:
        return bool(self.targets)

    @property
    def confidence(self) -> float:
        return max((t.confidence for t in self.targets), default=0.0)


class TemplateCache:
    """Loads template PNGs once and rescales them for the current client height."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, float], np.ndarray | None] = {}

    def get(self, path: str, ref_h: int, client_h: int) -> np.ndarray | None:
        if not path:
            return None
        p = Path(path)
        try:
            mtime = p.stat().st_mtime
        except OSError:
            return None
        scale = (client_h / ref_h) if ref_h > 0 else 1.0
        key = (f"{p}:{mtime}", round(scale, 3))
        if key not in self._cache:
            img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if img is not None and abs(scale - 1.0) > 0.01:
                img = cv2.resize(img, None, fx=scale, fy=scale,
                                 interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
            if img is None:
                log.warning("Template %s could not be loaded", p)
            self._cache[key] = img
        return self._cache[key]


def match_template(crop: np.ndarray, template: np.ndarray, threshold: float, max_hits: int = 6) -> list[tuple[int, int, float]]:
    """Return up to ``max_hits`` (cx, cy, score) matches in crop pixel coordinates."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    th, tw = template.shape[:2]
    if gray.shape[0] < th or gray.shape[1] < tw:
        return []
    scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    hits = []
    for _ in range(max_hits):
        _, score, _, loc = cv2.minMaxLoc(scores)
        if score < threshold:
            break
        x, y = loc
        hits.append((x + tw // 2, y + th // 2, float(score)))
        cv2.rectangle(scores, (max(0, x - tw // 2), max(0, y - th // 2)), (x + tw // 2, y + th // 2), -1.0, -1)
    return hits


def shake_color_mask(crop: np.ndarray, cfg: DetectionConfig) -> np.ndarray:
    return color_mask(crop, cfg.shake_color, cfg.shake_tolerance)


def detect_shake(frame: Frame, region: Region, cfg: DetectionConfig, templates: TemplateCache | None = None,
                 exclude: np.ndarray | None = None) -> ShakeResult:
    """Find shake buttons. ``exclude`` is a mask of shake-coloured background that
    was already on screen before the bite (white scenery, UI) and must be ignored."""
    crop = frame.crop(region)
    if crop is None or crop.size == 0:
        return ShakeResult()
    cw, ch = frame.client_size
    rx, ry, rw, rh = region.to_rect(cw, ch)
    h, w = crop.shape[:2]
    out = ShakeResult()

    template = templates.get(cfg.shake_template, cfg.shake_template_ref_h, ch) if (templates and cfg.shake_template) else None
    if template is not None:
        th, tw = template.shape[:2]
        for cx, cy, score in match_template(crop, template, cfg.template_threshold):
            out.targets.append(Target((rx + cx) / cw, (ry + cy) / ch, tw / cw, th / ch, _clamp(score)))
        return out

    mask = shake_color_mask(crop, cfg)
    if exclude is not None and exclude.shape == mask.shape:
        mask = cv2.bitwise_and(mask, cv2.bitwise_not(exclude))
    k = max(3, int(round(min(w, h) * 0.01)) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    n, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    area_total = float(w * h)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        frac = area / area_total
        if not (cfg.shake_min_area <= frac <= cfg.shake_max_area):
            continue
        aspect = bw / max(1, bh)
        if not (0.35 <= aspect <= 3.5):
            continue
        solidity = area / float(max(1, bw * bh))
        if solidity < 0.3:
            continue
        conf = _clamp(0.4 + solidity * 0.7)
        cx, cy = centroids[i]
        out.targets.append(Target((rx + x + bw / 2) / cw, (ry + y + bh / 2) / ch, bw / cw, bh / ch, conf))
    out.targets.sort(key=lambda t: -t.confidence)
    return out


# --------------------------------------------------------------------------- dialogs / popups

@dataclass
class DialogResult:
    detected: bool = False
    confidence: float = 0.0
    reason: str = ""


def detect_disconnect(crop: np.ndarray | None, cfg: DetectionConfig) -> DialogResult:
    """Heuristic: Roblox error dialogs are a large flat panel of one dark grey."""
    if crop is None or crop.size == 0 or not cfg.disconnect_detection:
        return DialogResult()
    mask = color_mask(crop, cfg.dialog_color, cfg.dialog_tolerance)
    fill = float(mask.mean()) / 255.0
    if fill >= cfg.dialog_min_fill:
        return DialogResult(True, _clamp(fill), "error dialog colour")
    return DialogResult(False, _clamp(fill), "")


def detect_template_popup(crop: np.ndarray | None, path: str, ref_h: int, client_h: int,
                          threshold: float, templates: TemplateCache) -> DialogResult:
    if crop is None or not path:
        return DialogResult()
    template = templates.get(path, ref_h, client_h)
    if template is None:
        return DialogResult()
    hits = match_template(crop, template, threshold, max_hits=1)
    if hits:
        return DialogResult(True, hits[0][2], "template")
    return DialogResult()
