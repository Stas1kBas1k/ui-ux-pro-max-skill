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


def shape_fish(crop: np.ndarray, bounds: tuple[int, int] | None = None) -> tuple[float, float, int] | None:
    """Find the fish marker by shape, whatever its colour: a thin line that runs most of the bar's height
    and differs from the track on both sides. Returns (x 0..1, confidence, width px) or None."""
    h, w = crop.shape[:2]
    if w < 40 or h < 6:
        return None
    img = crop.astype(np.int16)
    k = max(3, int(0.02 * w))
    mid = img[:, k:w - k]
    left, right = img[:, :w - 2 * k], img[:, 2 * k:]
    dl = np.abs(mid - left).max(axis=2)
    dr = np.abs(mid - right).max(axis=2)
    stands_out = np.minimum(dl, dr) > 38
    score = np.zeros(w, np.float32)
    score[k:w - k] = stands_out.mean(axis=0)
    margin = int(0.04 * w)  # frame decoration lives at the ends
    lo, hi = bounds if bounds else (margin, w - margin)
    score[:max(0, lo)] = 0
    score[min(w, hi):] = 0
    runs = [r for r in _runs(score >= 0.55, max_gap=max(1, int(0.008 * w))) if r[1] - r[0] <= max(3, int(0.03 * w))]
    if not runs:
        return None
    best = max(runs, key=lambda r: float(score[r[0]:r[1]].sum()) * float(score[r[0]:r[1]].max()))
    peak = float(score[best[0]:best[1]].max())
    weights = score[best[0]:best[1]]
    cx = float(np.average(np.arange(best[0], best[1]), weights=weights)) + 0.5
    # a second line just as strong elsewhere makes it ambiguous
    others = [float(score[a:b].max()) for a, b in runs if (a, b) != best and abs((a + b) / 2 - cx) > 0.05 * w]
    conf = _clamp((peak - 0.4) / 0.4) * (0.6 if others and max(others) >= peak - 0.05 else 1.0)
    return cx / w, conf, best[1] - best[0]


def detect_reel(crop: np.ndarray | None, cfg: DetectionConfig) -> ReelResult:
    if crop is None or crop.size == 0:
        return ReelResult()
    h, w = crop.shape[:2]
    res = ReelResult()

    fish = color_mask(crop, cfg.fish_color, cfg.fish_tolerance)
    fish_fill = fish.sum(axis=0, dtype=np.float32) / (255.0 * h)
    if getattr(cfg, "fish_tolerance2", 0) > 0:
        # per colour, then the larger: thin frame borders in each colour must not add up to a "fish"
        dark = color_mask(crop, cfg.fish_color2, cfg.fish_tolerance2)
        fish_fill = np.maximum(fish_fill, dark.sum(axis=0, dtype=np.float32) / (255.0 * h))
    fish_cols = fish_fill >= 0.2
    # bridge small gaps so a marker drawn as two outlines counts as one fish
    fish_runs = _runs(fish_cols, max_gap=max(1, int(0.012 * w)))
    if fish_runs:
        # The fish is the strongest compact cluster spanning the full bar height; wide or short clusters
        # (frame decoration, background) score lower.
        best = max(fish_runs, key=lambda r: float(fish_fill[r[0]:r[1]].sum()) * float(fish_fill[r[0]:r[1]].max()) ** 3
                   / max(1.0, (r[1] - r[0]) ** 0.25))
        width = best[1] - best[0]
        if width <= max(4, 0.25 * w):
            weights = fish_fill[best[0]:best[1]]
            cx = float(np.average(np.arange(best[0], best[1]), weights=weights)) + 0.5
            res.fish_found = True
            res.fish_x = cx / w
            res.fish_confidence = _clamp(float(weights.max()) / 0.55) * _clamp(width / 2.0)

    if getattr(cfg, "fish_any_colour", False):
        found = shape_fish(crop)
        if found is not None and found[1] >= 0.5:
            fx, fconf, fw = found
            if not res.fish_found or abs(res.fish_x - fx) > 0.03 or fconf > res.fish_confidence:
                res.fish_found, res.fish_x, res.fish_confidence = True, fx, fconf
                fish_cols = np.zeros(w, bool)
                c0 = int(fx * w)
                fish_cols[max(0, c0 - fw):c0 + fw + 1] = True

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
        if width < 0.97 * w or res.fish_found:  # a fully white region with no fish is not a catch bar
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
    if not res.ui_present and res.fish_found and res.fish_confidence >= 0.9 and getattr(cfg, "fish_tolerance2", 0) > 0:
        # Skinned frames (e.g. Plaguereaver) outline the track with a dark line across the whole width.
        dark = color_mask(crop, cfg.fish_color2, cfg.fish_tolerance2)
        if float((dark.sum(axis=1, dtype=np.float32) / (255.0 * w)).max()) >= 0.6:
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


def _progress_by_brightness(prof: np.ndarray, w: int) -> FillResult:
    """Both ends look alike (a frame around the bar): the filled part is the brighter one on the left."""
    v = prof.max(axis=2).mean(axis=0).astype(np.float32)
    m = max(3, int(0.06 * w))
    inner = v[m:w - m]
    n = inner.size
    if n < 10:
        return FillResult()
    c = np.concatenate(([0.0], np.cumsum(inner)))
    k = np.arange(1, n)
    gap = c[k] / k - (c[n] - c[k]) / (n - k)
    i = int(gap.argmax())
    if gap[i] < 20:
        return FillResult()
    return FillResult(True, _clamp((i + 1) / n), _clamp(gap[i] / 60.0))


def detect_progress_auto(crop: np.ndarray | None) -> FillResult:
    """Colour-free progress: the bar fills from the left, so find the split between the left look and
    the right look that explains the columns best. Unreadable (present=False) when both ends look alike."""
    if crop is None or crop.size == 0 or crop.shape[1] < 20:
        return FillResult()
    h, w = crop.shape[:2]
    y0, y1 = int(h * 0.25), max(int(h * 0.25) + 1, int(h * 0.75))
    prof = cv2.resize(crop[y0:y1], (w, 3), interpolation=cv2.INTER_AREA).astype(np.int16)
    e = max(2, int(0.04 * w))
    left, right = np.median(prof[:, :e], axis=1), np.median(prof[:, -e:], axis=1)
    if float(np.abs(left - right).max(axis=1).mean()) < 30:
        return _progress_by_brightness(prof, w)
    dl = np.abs(prof - left[:, None, :]).max(axis=2).mean(axis=0)
    dr = np.abs(prof - right[:, None, :]).max(axis=2).mean(axis=0)
    # cost of splitting at k: columns before k should look like the left end, after k like the right end
    cost = np.concatenate(([0.0], np.cumsum(dl))) + np.concatenate((np.cumsum(dr[::-1])[::-1], [0.0]))
    k = int(cost.argmin())
    worst = float(cost[k]) / w
    return FillResult(True, _clamp(k / w), _clamp(1.0 - worst / 40.0))


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
