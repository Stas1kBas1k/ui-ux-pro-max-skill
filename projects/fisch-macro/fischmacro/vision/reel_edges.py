"""Reel reading from edges, for skins whose colours say nothing (built from the player's recording).

What every reel skin seen so far has in common (normal, Stellarwave, MiguRod, Lullaby, Plaguereaver):

* the catch bar is a block with sharp left and right edges over the full height of the track, whatever
  its colour (Lullaby recolours it pink / green / red while you play; Stellarwave's track is full of
  zodiac glyphs, which only cover part of the height);
* the fish is a thin straight line, the strongest close pair of full-height edges, sticking out above and
  below the track (MiguRod's "!" marks sit inside the track).

So: measure, per column, on how many rows there is a strong left/right change; peaks are edges. The fish
is the best narrow pair; the bar is the pair that encloses a block that differs from what is just outside
it on both sides in the same way.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class EdgeReel:
    fish_x: float | None = None        # fraction of the crop width
    fish_conf: float = 0.0
    bar: tuple[float, float] | None = None
    bar_conf: float = 0.0
    extent: tuple[float, float] | None = None  # the track's ends


def edge_strength(crop: np.ndarray, thr: int = 40) -> np.ndarray:
    """Per column: share of rows with a strong horizontal colour change there."""
    c = crop.astype(np.int16)
    gx = np.abs(c[:, 2:, :] - c[:, :-2, :]).max(axis=2)
    f = (gx > thr).mean(axis=0)
    return np.concatenate([[0.0], f, [0.0]])


def _peaks(f: np.ndarray, lo: float) -> list[int]:
    """Columns where an edge is; a flat-topped edge several pixels wide counts once (its middle)."""
    idx = []
    i, n = 1, len(f) - 1
    while i < n:
        if f[i] >= lo and f[i] >= f[i - 1] and f[i] >= f[i + 1]:
            j = i
            while j + 1 < n and f[j + 1] == f[i]:
                j += 1
            c = (i + j) // 2
            if idx and c - idx[-1] <= 2:
                if f[c] > f[idx[-1]]:
                    idx[-1] = c
            else:
                idx.append(c)
            i = j + 1
        else:
            i += 1
    return idx


def find_fish(f: np.ndarray, w: int, img: np.ndarray | None = None) -> tuple[float, float, int] | None:
    """(x, confidence, half width) of the best narrow pair of strong edges. With ``img`` (the crop ``f`` came
    from), red lines are penalised: MiguRod's slash effect is a red line that also crosses the track."""
    red = None
    if img is not None:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        # share of strongly red pixels per column (MiguRod's slash effect); other colours are left alone,
        # since a skin may well draw a coloured fish line
        red = (((hsv[..., 0] <= 8) | (hsv[..., 0] >= 172)) & (hsv[..., 1] >= 120)).mean(axis=0)
    max_gap = max(8, int(0.022 * w))
    pk = _peaks(f, 0.3)
    best = None
    for i, a in enumerate(pk):
        for b in pk[i + 1:]:
            gap = b - a
            if gap > max_gap:
                break
            if gap < 2:
                continue
            s = min(f[a], f[b])
            # a clean line: little edge activity right next to it (a slash or a glyph is a jagged cluster)
            ring = np.concatenate([f[max(0, a - max_gap):max(0, a - 2)], f[b + 3:b + max_gap]])
            clutter = float((ring >= 0.3).mean()) if ring.size else 0.0
            score = s - 0.5 * clutter
            if red is not None and b - a >= 2:
                score -= 0.6 * float(red[a + 1:b].mean())
            if best is None or score > best[0]:
                best = (score, (a + b) / 2, gap)
    if best is None or best[0] < 0.3:
        return None
    return best[1] / w, min(1.0, best[0] / 0.5), int(best[2] / 2) + 2


def line_candidates(f: np.ndarray, w: int, min_score: float = 0.3) -> list[tuple[float, float, int]]:
    """Every narrow pair of strong edges (thin lines), as (x in px, score, gap in px)."""
    max_gap = max(8, int(0.022 * w))
    pk = _peaks(f, 0.3)
    out = []
    for i, a in enumerate(pk):
        for b in pk[i + 1:]:
            gap = b - a
            if gap > max_gap:
                break
            if gap >= 2 and min(f[a], f[b]) >= min_score:
                out.append(((a + b) / 2, float(min(f[a], f[b])), gap))
    return out


def brightest_line(tall: np.ndarray) -> tuple[float, float] | None:
    """(x as a fraction, confidence) of the brightest thin line crossing the strip."""
    w = tall.shape[1]
    f = edge_strength(cv2.GaussianBlur(tall, (3, 1), 0))
    cands = line_candidates(f, w)
    if not cands:
        return None
    g = cv2.cvtColor(tall, cv2.COLOR_BGR2GRAY).astype(np.float32)
    best = None
    for x, score, gap in cands:
        a, b = int(x - gap / 2) + 1, int(x + gap / 2)
        if b <= a:
            continue
        lum = float(np.median(g[:, a:b]))
        if best is None or lum > best[0]:
            best = (lum, x, score)
    if best is None or best[0] < 150:
        return None
    return best[1] / w, min(1.0, best[2] / 0.5)


def _col_means(crop: np.ndarray) -> np.ndarray:
    h = crop.shape[0]
    mid = crop[int(h * 0.3):max(int(h * 0.3) + 1, int(h * 0.7))].astype(np.float32)
    return mid.mean(axis=0)  # (w, 3)


def find_bar(crop: np.ndarray, f: np.ndarray, fish: tuple[float, float, int] | None,
             prev: tuple[float, float] | None = None) -> tuple[tuple[int, int], float, tuple[int, int]] | None:
    """((left, right) in pixels, confidence, track extent)."""
    h, w = crop.shape[:2]
    pk = _peaks(f, 0.22)
    if fish is not None:
        fx, hw = fish[0] * w, fish[2]
        pk = [p for p in pk if abs(p - fx) > hw + 6]
    if len(pk) < 2:
        return None
    extent = (pk[0], pk[-1])
    span = max(1, extent[1] - extent[0])
    cols = _col_means(crop)
    lum = cols.mean(axis=1)
    d = max(3, int(0.006 * w))
    best = None
    for i, a in enumerate(pk):
        for b in pk[i + 1:]:
            width = b - a
            if width < 0.05 * span or width > 0.97 * span:
                continue
            ins_l, ins_r = lum[min(w - 1, a + d):min(w, a + 3 * d)], lum[max(0, b - 3 * d):max(1, b - d)]
            out_l, out_r = lum[max(0, a - 3 * d):max(1, a - d)], lum[min(w - 1, b + d):min(w, b + 3 * d)]
            if not (ins_l.size and ins_r.size):
                continue
            # contrast across each edge; at a track end there is no outside, so it only needs the inner side
            cl = (ins_l.mean() - out_l.mean()) if (out_l.size and a > extent[0] + d) else None
            cr = (ins_r.mean() - out_r.mean()) if (out_r.size and b < extent[1] - d) else None
            sides = [c for c in (cl, cr) if c is not None]
            if not sides:
                continue
            if len(sides) == 1:
                # against a track end: the rest of the track must be one plain look that the block differs from
                rest = np.concatenate([lum[extent[0] + d:a - d], lum[b + d:extent[1] - d]])
                if rest.size < 0.1 * span:
                    continue
                inner = lum[a + d:b - d]
                if np.percentile(rest, 90) - np.percentile(rest, 10) > 45:
                    continue  # the rest is not plain: this is not "bar + empty track"
                sides = [float(np.median(inner) - np.median(rest))]
            if len(sides) == 2 and np.sign(sides[0]) != np.sign(sides[1]):
                continue  # brighter on one side, darker on the other: a step, not a block
            contrast = min(abs(c) for c in sides)
            if contrast < 12:
                continue
            # the inside of a bar is one block: its colour drifts little compared with the jumps at its edges
            inside = cols[a + d:b - d]
            drift = float(np.abs(np.diff(inside, axis=0)).max(axis=1).mean()) if len(inside) > 2 else 99.0
            score = (f[a] + f[b]) + min(contrast, 80) / 80 - drift / 30
            if cl is not None and cr is not None:
                score += 0.6  # both edges inside the track: the most certain kind of bar
            if prev is not None:
                pc = (prev[0] + prev[1]) / 2 * w
                score -= 0.5 * abs((a + b) / 2 - pc) / w
            if best is None or score > best[0]:
                best = (score, (a, b))
    if best is None:
        return None
    return best[1], max(0.0, min(1.0, best[0] / 2.0)), extent


class EdgeReelTracker:
    """Keeps the last bar so a frame with an ambiguous pair picks the one nearest to where the bar was."""

    def __init__(self) -> None:
        self.prev: tuple[float, float] | None = None

    def reset(self) -> None:
        self.prev = None

    def update(self, crop: np.ndarray | None, tall: np.ndarray | None = None) -> EdgeReel:
        """``crop``: the track; ``tall``: the same columns with extra rows above and below, where only the
        fish line continues (better fish separation from glyphs, marks and bar edges)."""
        out = EdgeReel()
        if crop is None or crop.size == 0 or crop.shape[1] < 60:
            return out
        h, w = crop.shape[:2]
        f = edge_strength(cv2.GaussianBlur(crop, (3, 1), 0))
        ft = edge_strength(cv2.GaussianBlur(tall, (3, 1), 0)) if tall is not None and tall.shape[1] == w else f
        fish = find_fish(ft, w)
        if fish is not None:
            out.fish_x, out.fish_conf = fish[0], fish[1]
        bar = find_bar(crop, f, fish, self.prev)
        if bar is not None:
            (a, b), conf, ext = bar
            out.bar, out.bar_conf, out.extent = (a / w, b / w), conf, (ext[0] / w, ext[1] / w)
            self.prev = out.bar
        return out


def find_marks(crop: np.ndarray, fish_x: float | None, bar: tuple[float, float] | None) -> list[float]:
    """Thin features standing on the track that are not the fish and not part of the bar: MiguRod's "!"
    marks, where a slash will land (player recording, 29.0-30.0 s). Fractions of the crop width."""
    h, w = crop.shape[:2]
    f = edge_strength(cv2.GaussianBlur(crop, (3, 1), 0))
    pk = _peaks(f, 0.45)
    if len(pk) < 2:
        return []
    lo, hi = pk[0], pk[-1]  # the track's ends
    out = []
    max_gap = max(8, int(0.02 * w))
    for i, a in enumerate(pk):
        for b in pk[i + 1:]:
            if b - a > max_gap:
                break
            c = (a + b) / 2 / w
            if a - lo < 0.03 * w or hi - b < 0.03 * w:
                continue
            if fish_x is not None and abs(c - fish_x) < 0.02:
                continue
            if bar is not None and bar[0] - 0.01 <= c <= bar[1] + 0.01:
                continue
            if not out or abs(c - out[-1]) > 0.02:
                out.append(c)
    return out


def dodge_aim(fish: float, bar_l: float, bar_r: float, marks: list[float], margin: float = 0.18) -> float:
    """Where to aim the bar's centre: on the fish, unless that puts a mark under the bar; then the nearest
    centre that keeps the fish inside the bar (with a margin) and every mark outside it. If no such centre
    exists the fish wins (losing the fish costs more than a slice of the bar)."""
    width = max(1e-3, bar_r - bar_l)
    half = width / 2
    pad = 0.15 * width

    def clear(c: float) -> bool:
        return all(not (c - half - pad <= m <= c + half + pad) for m in marks)
    if not marks or clear(fish):
        return fish
    lim = half - margin * width
    best = None
    for k in range(-40, 41):
        c = fish + lim * k / 40
        if clear(c) and (best is None or abs(c - fish) < abs(best - fish)):
            best = c
    return fish if best is None else best
