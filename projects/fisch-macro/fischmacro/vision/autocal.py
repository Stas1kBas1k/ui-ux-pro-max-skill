"""Automatic calibration: find the minigame UI and its colours without user input.

The reel minigame is the only wide horizontal strip in the lower half of the
screen where things move sideways for seconds at a time (the catch bar and the
fish), so a short buffer of frames is enough to locate it from motion alone.
Inside it, column colours separate into background, a wide bar run and a narrow
fish run; their medians become the detector colours. The same idea finds the
progress bar (a thin strip that fills below the reel) and the vertical cast
power bar. Re-sampling colours on every rod/skin change keeps detection working
without manual calibration.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from fischmacro.profiles.schema import Region
from fischmacro.vision.frame import bgr_to_hex

log = logging.getLogger(__name__)
WORK_WIDTH = 640  # frames are downscaled to this width for motion analysis


@dataclass
class AutoCalResult:
    reel: Region | None = None
    progress: Region | None = None
    cast: Region | None = None
    bar_color: str | None = None
    fish_color: str | None = None
    progress_color: str | None = None
    cast_color: str | None = None
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.reel is not None and self.bar_color is not None and self.fish_color is not None


def _small(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    if w <= WORK_WIDTH:
        return img
    s = WORK_WIDTH / w
    return cv2.resize(img, (WORK_WIDTH, max(1, int(h * s))), interpolation=cv2.INTER_AREA)


def motion_map(frames: list[np.ndarray]) -> np.ndarray:
    """Per-pixel range (max - min) across frames, taking the strongest colour channel.

    Colour, not brightness: a dark red fish on a dark grey bar has almost the same
    grey level but a very different red channel.
    """
    stack = np.stack(frames)
    return (stack.max(axis=0) - stack.min(axis=0)).max(axis=2).astype(np.uint8)


def _components(mask: np.ndarray, kernel: tuple[int, int]) -> list[tuple[int, int, int, int, int]]:
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, kernel))
    n, _, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    return [tuple(int(v) for v in stats[i]) for i in range(1, n)]


def _container_extent(frames: list[np.ndarray], x: int, x1: int, y: int, y1: int) -> tuple[int, int]:
    """Widen a motion box to the full static container.

    The palette of colours seen inside the moving strip (container background,
    catch bar, fish) is collected over all frames; columns are added on both
    sides while their colour belongs to that palette. This also crosses a bar
    that is parked against a wall, and stops at the container border.
    """
    band = np.stack([f[y:y1] for f in frames]).astype(np.float32)      # (t, rows, w, 3)
    per_frame = np.median(band, axis=1)                                 # (t, w, 3)
    inside = per_frame[:, x:x1].reshape(-1, 3)
    if inside.size == 0:
        return x, x1
    q = (inside // 12).astype(int)
    keys = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
    uniq, counts = np.unique(keys, return_counts=True)
    palette = [np.median(inside[keys == k], axis=0) for k, c in zip(uniq, counts) if c >= 0.03 * len(keys)]
    if not palette:
        return x, x1
    pal = np.stack(palette)                                             # (p, 3)
    cols = per_frame                                                    # (t, w, 3)
    # a column belongs to the strip if, in most frames, it matches some palette colour
    d = np.abs(cols[:, :, None, :] - pal[None, None, :, :]).max(axis=3).min(axis=2)   # (t, w)
    near = (d < 22).mean(axis=0) > 0.8
    w = near.shape[0]
    x0, x1n = x, x1
    while x0 > 0 and near[x0 - 1]:
        x0 -= 1
    while x1n < w and near[x1n]:
        x1n += 1
    return x0, x1n


def _tighten_rows(mask: np.ndarray, x: int, y: int, bw: int, bh: int) -> tuple[int, int]:
    rows = (mask[y:y + bh, x:x + bw] > 0).mean(axis=1)
    keep = np.flatnonzero(rows >= 0.5 * rows.max())
    if keep.size == 0:
        return y, bh
    return y + int(keep[0]), int(keep[-1] - keep[0] + 1)


def find_reel(frames: list[np.ndarray]) -> tuple[tuple[int, int, int, int] | None, float]:
    """Locate the reel strip (x, y, w, h) in work-scale pixels, with a confidence."""
    if len(frames) < 4:
        return None, 0.0
    mm = motion_map(frames)
    h, w = mm.shape
    mask = (mm > 30).astype(np.uint8) * 255
    mask[: int(h * 0.45)] = 0  # the reel UI sits in the lower part of the screen
    # The bar and fish change whole columns of the strip; waves and particles are thin.
    # A vertical opening removes thin horizontal motion before grouping.
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(4, h // 90))))
    best, best_score = None, 0.0
    for x, y, bw, bh, area in _components(mask, (max(3, w // 40), 3)):
        if bw < 0.12 * w or bw > 0.9 * w or bh < 3 or bw / max(1, bh) < 5:
            continue
        fill = area / float(bw * bh)
        score = bw / w * min(1.0, fill * 2)
        if score > best_score:
            best, best_score = (x, y, bw, bh), score
    if best is None:
        return None, 0.0
    x, y, bw, bh = best
    y, bh = _tighten_rows(mask, x, y, bw, bh)
    x0, x1 = _container_extent(frames, x, x + bw, y, y + bh)
    if x1 - x0 > 0.9 * w:  # ran into the scenery; trust the motion box
        x0, x1 = x, x + bw
    return (x0, y, x1 - x0, bh), min(1.0, 0.4 + best_score)


def find_progress(frames: list[np.ndarray], reel: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    """A thin strip just below the reel whose content changed (it fills up)."""
    mm = motion_map(frames)
    rx, ry, rw, rh = reel
    y_lo, y_hi = ry + rh + 1, min(mm.shape[0], ry + rh + 4 * rh + 6)
    if y_hi - y_lo < 2:
        return None
    sub = (mm[y_lo:y_hi] > 30).astype(np.uint8) * 255
    best = None
    for x, y, bw, bh, area in _components(sub, (5, 1)):
        if bw < 0.05 * rw or bh > rh or bh < 2:
            continue
        if x < rx - 0.1 * rw or x + bw > rx + 1.1 * rw:
            continue  # moving scenery (waves) is not aligned with the reel
        # a progress fill changes a solid block; a passing wave line is sparse
        if area / float(bw * bh) < 0.6:
            continue
        if best is None or bw * bh > best[2] * best[3]:
            best = (x, y + y_lo, bw, bh)
    if best is None:
        return None
    x, y, bw, bh = best
    # the fill moves along the track: extend to the static ends of the track
    x0, x1 = _container_extent(frames, x, x + bw, y, y + bh)
    if x1 - x0 > 1.2 * rw:
        x0, x1 = x, x + bw
    return (x0, y, x1 - x0, bh)


def find_cast(frames: list[np.ndarray]) -> tuple[int, int, int, int] | None:
    """The vertical power bar that fills while the cast is charging."""
    if len(frames) < 3:
        return None
    mm = motion_map(frames)
    h, w = mm.shape
    mask = (mm > 30).astype(np.uint8) * 255
    mask[:, : int(w * 0.2)] = 0
    mask[:, int(w * 0.8):] = 0
    mask[int(h * 0.8):] = 0
    best = None
    for x, y, bw, bh, area in _components(mask, (3, 5)):
        if bh < 0.06 * h or bh / max(1, bw) < 3 or area / float(bw * bh) < 0.5:
            continue
        if best is None or bh > best[3]:
            best = (x, y, bw, bh)
    return best


def sample_reel_colors_multi(crops: list[np.ndarray]) -> tuple[str | None, str | None, float]:
    """Sample several frames and keep the most common confident answer."""
    votes: dict[tuple[str | None, str | None], float] = {}
    for c in crops:
        bar, fish, conf = sample_reel_colors(c)
        if bar and fish:
            votes[(bar, fish)] = votes.get((bar, fish), 0.0) + conf
    if not votes:
        return sample_reel_colors(crops[-1]) if crops else (None, None, 0.0)
    (bar, fish), score = max(votes.items(), key=lambda kv: kv[1])
    return bar, fish, min(1.0, score / max(1, len(crops)) * 2)


def sample_reel_colors(crop: np.ndarray) -> tuple[str | None, str | None, float]:
    """(bar_hex, fish_hex, confidence) from one reel crop."""
    if crop is None or crop.size == 0:
        return None, None, 0.0
    h, w = crop.shape[:2]
    band = crop[int(h * 0.3): max(int(h * 0.3) + 1, int(h * 0.7))]
    m = max(1, int(w * 0.02))  # skip the container border at both ends
    band = band[:, m:w - m]
    w = band.shape[1]
    cols = np.median(band, axis=0).astype(np.float32)  # (w, 3)
    # background = the most common column colour (the bar can sit at either end)
    q = (cols // 16).astype(int)
    keys = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    bg = np.median(cols[keys == np.bincount(keys).argmax()], axis=0)
    dist = np.abs(cols - bg).max(axis=1)
    fg = dist > 22
    if fg.sum() < max(4, 0.03 * w):
        return None, None, 0.0
    fg_cols = cols[fg]
    _, labels, centers = cv2.kmeans(fg_cols, 2, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5),
                                    3, cv2.KMEANS_PP_CENTERS)
    labels = labels.ravel()
    counts = np.bincount(labels, minlength=2)
    bar_i = int(np.argmax(counts))
    fish_i = 1 - bar_i
    if counts[fish_i] == 0 or np.abs(centers[0] - centers[1]).max() < 22:
        return bgr_to_hex(centers[bar_i]), None, 0.3
    if counts[fish_i] > 0.6 * counts[bar_i]:
        return None, None, 0.0  # no clear wide bar + narrow fish split
    bar = np.median(fg_cols[labels == bar_i], axis=0)
    fish = np.median(fg_cols[labels == fish_i], axis=0)
    conf = min(1.0, counts[bar_i] / (0.08 * w)) * min(1.0, np.abs(bar - fish).max() / 60)
    return bgr_to_hex(bar), bgr_to_hex(fish), float(conf)


def sample_changed_color(frames: list[np.ndarray], rect: tuple[int, int, int, int]) -> str | None:
    """Median colour of pixels that changed inside rect (fill colour of a growing bar)."""
    x, y, w, h = rect
    first, last = frames[0][y:y + h, x:x + w], None
    # use the frame with the largest change versus the first one
    best, best_n = None, 0
    for f in frames[1:]:
        crop = f[y:y + h, x:x + w]
        diff = cv2.absdiff(crop, first).max(axis=2) > 40
        n = int(diff.sum())
        if n > best_n:
            best, best_n, last = diff, n, crop
    if best is None or best_n < 4:
        return None
    # Changed pixels hold the fill colour in one frame and the empty track in the other.
    # The empty track also shows at the far right end of the strip, so pick the other one.
    track = np.median(first[:, -max(2, w // 20):].reshape(-1, 3), axis=0)
    a = np.median(first[best], axis=0)
    b = np.median(last[best], axis=0)
    fill = a if np.abs(a - track).max() > np.abs(b - track).max() else b
    return bgr_to_hex(fill)


def _to_region(rect, size, pad: int = 1) -> Region:
    x, y, w, h = rect
    W, H = size
    x, y = max(0, x - pad), max(0, y - pad)
    return Region(x / W, y / H, min(W - x, w + 2 * pad) / W, min(H - y, h + 2 * pad) / H, True)


def calibrate(frames: list[np.ndarray], cast_frames: list[np.ndarray] | None = None) -> AutoCalResult:
    """Run the full auto-calibration on full-client frames (BGR, any size)."""
    res = AutoCalResult()
    if len(frames) < 4:
        res.notes.append("not enough frames")
        return res
    small = [_small(f) for f in frames]
    size = (small[0].shape[1], small[0].shape[0])
    reel, conf = find_reel(small)
    if reel is not None:
        # Drop frames from before the minigame appeared: there the strip still shows scenery.
        x, y, w, h = reel
        last = small[-1][y:y + h, x:x + w].astype(np.float32)
        keep = [i for i, f in enumerate(small)
                if np.abs(f[y:y + h, x:x + w].astype(np.float32).mean(axis=(0, 1)) - last.mean(axis=(0, 1))).max() < 25]
        if 4 <= len(keep) < len(small):
            small = [small[i] for i in keep]
            frames = [frames[i] for i in keep]
            reel, conf = find_reel(small)
    if reel is not None:
        res.reel = _to_region(reel, size)
        res.confidence = conf
        # sample colours at full resolution from several recent frames
        H, W = frames[-1].shape[:2]
        x, y, w, h = res.reel.to_rect(W, H)
        bar, fish, cconf = sample_reel_colors_multi([f[y:y + h, x:x + w] for f in frames[-8:]])
        res.bar_color, res.fish_color = bar, fish
        res.confidence *= max(0.3, cconf)
        prog = find_progress(small, reel)
        if prog is not None:
            res.progress = _to_region(prog, size, pad=0)
            res.progress_color = sample_changed_color(small, prog)
        else:
            res.notes.append("progress bar not found (no fill change seen yet)")
    else:
        res.notes.append("reel minigame not found - start a minigame and let it run a few seconds")
    if cast_frames:
        cs = [_small(f) for f in cast_frames]
        cast = find_cast(cs)
        if cast is not None:
            res.cast = _to_region(cast, (cs[0].shape[1], cs[0].shape[0]), pad=0)
            res.cast_color = sample_changed_color(cs, cast)
    return res


class AutoCalibrator:
    """Keeps a short rolling buffer of downscaled full frames and calibrates on demand."""

    def __init__(self, seconds: float = 4.0, fps: float = 12.0):
        self.seconds = seconds
        self.period = 1.0 / fps
        self.frames: deque[tuple[float, np.ndarray]] = deque()
        self.full_frames: deque[np.ndarray] = deque(maxlen=3)  # full resolution, for validation
        self._last_add = -1e9
        self.active = False

    def wants_frame(self, now: float) -> bool:
        return self.active and now - self._last_add >= self.period

    def add(self, image: np.ndarray, now: float) -> None:
        self._last_add = now
        self.full_frames.append(image)
        self.frames.append((now, _small(image).copy()))
        while self.frames and now - self.frames[0][0] > self.seconds:
            self.frames.popleft()

    def clear(self) -> None:
        self.frames.clear()
        self.full_frames.clear()

    def validate(self, profile, res: AutoCalResult) -> bool:  # noqa: C901
        """Accept a result only if the real detectors then see a confident fish + bar."""
        if not res.ok or not self.full_frames:
            return False
        import copy

        from fischmacro.vision.engine import VisionEngine
        from fischmacro.vision.frame import Frame
        trial = copy.deepcopy(profile)
        apply_result(trial, res)
        engine = VisionEngine(trial)
        good = 0
        for img in self.full_frames:
            obs = engine.process(Frame(img, (img.shape[1], img.shape[0])), ("reel",))
            r = obs.reel
            # a real fish is inside the strip, not on its border
            good += r.present and r.confidence >= 0.6 and 0.01 < r.fish_x < 0.99
        return good >= max(1, len(self.full_frames) - 1)

    def run(self) -> AutoCalResult:
        t0 = time.perf_counter()
        res = calibrate([f for _, f in self.frames])
        log.debug("auto-calibration took %.0f ms: %s", (time.perf_counter() - t0) * 1000, res)
        return res


def apply_result(profile, res: AutoCalResult, regions: bool = True) -> list[str]:
    """Write a result into a profile; returns a human readable list of what changed."""
    changed = []
    d = profile.detection
    if regions and res.reel is not None:
        profile.regions["reel"] = res.reel
        changed.append("reel region")
    if regions and res.progress is not None:
        profile.regions["progress"] = res.progress
        changed.append("progress region")
    if regions and res.cast is not None:
        profile.regions["cast"] = res.cast
        changed.append("cast region")
    for attr, value in (("bar_color", res.bar_color), ("fish_color", res.fish_color),
                        ("progress_color", res.progress_color), ("cast_color", res.cast_color)):
        if value and getattr(d, attr) != value:
            setattr(d, attr, value)
            changed.append(attr.replace("_", " "))
    if res.bar_color:
        d.bar_tolerance2 = 0  # the sampled colour is exact; the generic grey could match this skin's track
    return changed
