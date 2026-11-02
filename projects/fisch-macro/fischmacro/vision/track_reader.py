"""The catch bar, read the way every skin in the player's recordings draws it.

Built from the player's recordings (Halibut Crimson Excision, Remembrance Living / Departed, Doomsekkar, MiguRod,
basic rods). What all of them share:

* every reel starts with the bar centred on the track, and the bar keeps its width for the whole reel;
* decorations (fangs, pumpkins, roses, arrows, the fish line, "!" marks) are narrow compared with the bar, or
  stick out above / below the track;
* skins draw the track a little higher or lower: on Remembrance the saved reel area lay entirely below the track.

So: while the bar sits centred at the start, find the height at which a centred block with clear left and right
edges shows best, and its width. Remember what the empty track looks like there. From then on the bar is the
window of that width that looks least like the empty track (with its two edges on clear changes), near where it
was. The detectors used before (colour, shape) read the bar wrong on 19 of 29 labelled frames of those
recordings; this reads 24 right.
"""
from __future__ import annotations

import cv2
import numpy as np

ROWS = 8


def _profile(crop: np.ndarray) -> np.ndarray:
    h, w = crop.shape[:2]
    y0, y1 = int(h * 0.2), max(int(h * 0.2) + 1, int(h * 0.8))
    return cv2.resize(crop[y0:y1], (w, ROWS), interpolation=cv2.INTER_AREA).astype(np.float32)


def _coldist(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    return np.abs(p - q).max(axis=2).mean(axis=0)


def line_columns(tall: np.ndarray | None, w: int) -> np.ndarray:
    """Columns where something continues above or below the track (the fish line, marks, icons): never a bar
    edge."""
    if tall is None or tall.shape[1] != w or tall.shape[0] < 8:
        return np.zeros(w, bool)
    from fischmacro.vision.reel_edges import edge_strength
    k = max(3, int(tall.shape[0] * 0.25))
    out = np.maximum(edge_strength(cv2.GaussianBlur(tall[:k], (3, 1), 0), thr=35),
                     edge_strength(cv2.GaussianBlur(tall[-k:], (3, 1), 0), thr=35))
    hit = out > 0.35
    grown = hit.copy()
    for s_ in range(1, 7):  # a line is a few pixels wide: cover it and its sides
        grown[s_:] |= hit[:-s_]
        grown[:-s_] |= hit[s_:]
    return grown


def centred_pair(P: np.ndarray, lines: np.ndarray | None = None) -> tuple[float, int, int]:
    """(score, left, right) of the clearest block centred on the strip: a clear change of look at both ends,
    the look steady just outside them."""
    w = P.shape[1]
    c, d = w // 2, 4
    hws = np.arange(int(0.04 * w), int(0.46 * w))
    a, b = c - hws, c + hws
    ok = (a - 3 * d >= 0) & (b + 3 * d < w)
    a, b, hws = a[ok], b[ok], hws[ok]
    if len(hws) == 0:
        return 0.0, 0, 0
    jump = lambda i, j: np.abs(P[:, i] - P[:, j]).max(axis=2).mean(axis=0)  # noqa: E731 - (ROWS, n, 3) -> (n,)
    jl, jr = jump(a + d, a - d), jump(b - d, b + d)
    sl, sr = jump(a - d, a - 3 * d), jump(b + d, b + 3 * d)
    s = np.minimum(jl, jr) - 0.5 * (sl + sr)
    if lines is not None and lines.any():
        s = np.where(lines[a] | lines[b], -1e9, s)  # an edge made by the fish line is not a bar edge
    # an icon riding inside the bar (Halibut Crimson Excision's fang, a skin's arrows) is narrower than the bar:
    # of the clear centred blocks, the widest is the bar
    top = float(s.max())
    strong = np.flatnonzero(s >= 0.7 * top) if top > 0 else np.array([int(np.argmax(s))])
    k = int(strong[np.argmax(hws[strong])])
    return float(s[k]), int(a[k]), int(b[k])


class TrackReader:
    # up / down shifts of the reel area tried (fraction of the height). Below the saved area sits the progress bar,
    # which a downward shift mistook for the track; skins seen so far draw the track at it or higher (Remembrance)
    OFFSETS = tuple(np.round(np.arange(-0.06, 0.0121, 0.006), 4))

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.dy: float | None = None
        self.W: int | None = None
        self.x: int | None = None
        self.T: np.ndarray | None = None
        self.known: np.ndarray | None = None
        self.n = 0
        self.buf: dict[float, list[np.ndarray]] = {}
        self.cands: list[tuple[float, float, int]] = []
        self.lock_score = 0.0
        self.better = 0
        self.conf = 0.0

    @property
    def locked(self) -> bool:
        return self.W is not None

    def update(self, crop_at, tall_at=None) -> tuple[float, float, float] | None:
        """``crop_at(dy)`` returns the reel area shifted by dy (fraction of the screen height) or None;
        ``tall_at(dy)`` the same with rows above and below. Returns (left, right, confidence) once locked."""
        self.n += 1
        if self.W is None or self.n < 120:
            self._look_for_the_start(crop_at, tall_at)
        if self.W is None:
            return None
        crop = crop_at(self.dy)
        if crop is None or crop.shape[1] != self.T.shape[1]:
            return None
        return self._follow(crop, tall_at(self.dy) if tall_at else None)

    # -- start: the bar is centred and still
    def _look_for_the_start(self, crop_at, tall_at=None) -> None:
        full = self.W is None or self.n % 3 == 0  # every height on these frames; only the chosen one in between
        offsets = self.OFFSETS if full else (self.dy,)
        best = None
        for dy in offsets:
            crop = crop_at(dy)
            if crop is None:
                continue
            frames = self.buf.setdefault(dy, [])
            frames.append(_profile(crop))
            del frames[:-4]
            if len(frames) < 4:
                continue
            # the median of the last frames: a bar that sits still shows clear edges, one already moving does not
            # (then nothing is locked and the other readers keep the bar)
            P = np.median(frames, axis=0)
            s, a, b = centred_pair(P)
            s *= 1.0 / (1.0 + 12.0 * abs(dy))  # the saved height first: another must be clearly better
            if best is None or s > best[0]:
                best = (s, dy, a, b, P)
        if best is None:
            return
        s, dy, a, b, P = best
        if self.W is None:
            self.cands.append((s, dy, b - a))
            last = self.cands[-4:]
            if len(last) == 4 and min(c[0] for c in last) > 12 and len({c[1] for c in last}) == 1 \
                    and max(c[2] for c in last) - min(c[2] for c in last) <= 0.015 * P.shape[1]:
                self._lock(dy, a, b, P, s)
        elif not full:
            return  # a comparison with the other heights waits for the next full look
        elif s > 1.5 * self.lock_score and (abs((b - a) - self.W) > 0.02 * P.shape[1] or dy != self.dy):
            # the reel fades in (or a decoration was taken before it showed): a much clearer centred block
            # replaces the first guess
            self.better += 1
            if self.better >= 3:
                self._lock(dy, a, b, P, s)
        else:
            self.better = 0

    def _lock(self, dy, a, b, P, s) -> None:
        w = P.shape[1]
        self.dy, self.W, self.x, self.lock_score, self.better = dy, b - a, a, s, 0
        self.T = P.copy()
        self.known = np.ones(w, bool)
        self.known[max(0, a - 3):b + 4] = False

    # -- every frame: the window of the bar's width that looks least like the empty track
    def _follow(self, crop: np.ndarray, tall) -> tuple[float, float, float]:
        w = crop.shape[1]
        P = _profile(crop)
        T = self.T
        if not self.known.all():
            idx = np.flatnonzero(self.known)
            if len(idx):
                near = idx[np.abs(np.arange(w)[:, None] - idx[None, :]).argmin(axis=1)]
                T = T.copy()
                T[:, ~self.known] = T[:, near[~self.known]]
        D = _coldist(P, T)
        E = np.zeros(w)
        E[4:-4] = np.abs(P[:, 8:] - P[:, :-8]).max(axis=2).mean(axis=0)
        W = self.W
        cs = np.concatenate([[0.0], np.cumsum(D)])
        xs = np.arange(0, w - W + 1)
        inside = (cs[xs + W] - cs[xs]) / W
        edges = (E[xs] + E[np.minimum(xs + W - 1, w - 1)]) / 2
        jump = np.maximum(0, np.abs(xs - self.x) - 0.06 * w)  # bars move fast: only big jumps are suspicious
        top = float(inside.max()) or 1.0
        score = inside + 0.5 * edges - 0.6 * jump / w * top
        x = int(xs[int(np.argmax(score))])
        self.x = x
        # the empty track was learned at the start; the strip under the starting bar is filled in once the bar
        # is well away (learning everywhere let a slightly wrong position teach the bar's look as "track")
        if not self.known.all():
            far = np.ones(w, bool)
            far[max(0, x - int(0.08 * w)):x + W + int(0.08 * w)] = False
            new = far & ~self.known
            if new.any():
                self.T[:, new] = P[:, new]
                self.known |= new
        outside = np.concatenate([D[:max(0, x - 4)], D[x + W + 4:]])
        contrast = float(inside[x] - (np.median(outside) if outside.size else 0.0))
        self.conf = float(np.clip(contrast / 40.0, 0.0, 1.0))
        lo, hi = x, x + W
        if self.shrink:
            lo, hi = self._cut_bar(D, x, W, w)
        return lo / w, hi / w, self.conf

    shrink = False  # MiguRod: slashes cut the bar shorter during the reel

    def _cut_bar(self, D: np.ndarray, x: int, W: int, w: int) -> tuple[int, int]:
        """The part of the window that really is bar (the rest looks like empty track); after a few frames the
        shorter width is kept."""
        seg = D[x:x + W]
        if seg.size < 8:
            return x, x + W
        good = seg > 0.5 * float(np.percentile(seg, 90))
        gap, best, start, miss = max(2, int(0.02 * w)), (0, 0), None, 0
        for i, g in enumerate(np.append(good, False)):
            if g:
                start = i if start is None else start
                miss = 0
            elif start is not None:
                miss += 1
                if miss > gap or i == len(good):
                    end = i - miss + 1
                    if end - start > best[1] - best[0]:
                        best = (start, end)
                    start, miss = None, 0
        a, b = best
        if b - a < 0.8 * W and b - a > 0.03 * w:
            self.short = getattr(self, "short", 0) + 1
            if self.short >= 4:
                self.W, self.x, self.short = b - a, x + a, 0
            return x + a, x + b
        self.short = 0
        return x, x + W
