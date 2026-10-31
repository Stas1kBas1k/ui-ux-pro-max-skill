"""Stellarwave zodiac reading (built from the player's recording, frames 16.5-21.3 s).

On screen: a fixed row of the 12 signs Aries..Pisces with a star under each, above the reel; the reel strip
holds the same signs in shuffled order. Picking the next sign in order (by clicking it on the strip) lights
its star. So:

* ``read_row`` finds the 12 signs of the top row and counts the lit stars from the left -> the next sign;
* ``find_on_strip`` finds that sign on the strip by shape, using the top-row sign itself as the template
  (whatever the skin draws, both rows are drawn the same way), at the strip's larger size.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius",
         "Capricorn", "Aquarius", "Pisces"]


@dataclass
class ZodiacRow:
    found: bool = False
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)  # glyph boxes in the search crop
    lit: int = 0                     # stars lit from the left = signs picked so far
    templates: list[np.ndarray] = field(default_factory=list)


@dataclass
class ZodiacObs:
    found: bool = False
    lit: int = 0
    next_sign: str = ""
    x: float = 0.0          # where the next sign is, client fraction
    y: float = 0.0
    score: float = 0.0
    margin: float = 0.0     # how much better than the next best place

    @property
    def confident(self) -> bool:
        return self.found and bool(self.next_sign) and self.score >= 0.4 and self.margin >= 0.06


@dataclass
class StripHit:
    x: float = 0.0                   # in the strip crop, pixels
    y: float = 0.0
    score: float = 0.0
    second: float = 0.0              # best score of a clearly different place (for confidence)


def _light(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return ((hsv[..., 2] > 170) & (hsv[..., 1] < 90)).astype(np.uint8)


def read_row(crop: np.ndarray) -> ZodiacRow:
    """``crop``: the area above the reel holding the sign row and the stars."""
    out = ZodiacRow()
    if crop is None or crop.size == 0:
        return out
    h, w = crop.shape[:2]
    light = _light(crop)
    joined = cv2.dilate(light, np.ones((3, 3), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    comps = [tuple(s[:4]) for s in st[1:] if 0.008 * w <= s[2] <= 0.06 * w and s[3] >= 0.06 * h and s[4] >= 12]
    if len(comps) < 10:
        return out
    # group by vertical centre; the sign row is the top-most group of 10-12 evenly spaced shapes
    comps.sort(key=lambda c: c[1] + c[3] / 2)
    groups: list[list[tuple]] = []
    for c in comps:
        cy = c[1] + c[3] / 2
        if groups and abs(cy - (groups[-1][-1][1] + groups[-1][-1][3] / 2)) < 0.06 * h:
            groups[-1].append(c)
        else:
            groups.append([c])
    for g in groups:
        g = _merge_slots(sorted(g, key=lambda c: c[0]))
        if not 10 <= len(g) <= 12:
            continue
        xs = np.array([c[0] + c[2] / 2 for c in g])
        gaps = np.diff(xs)
        step = float(np.median(gaps))
        ratio = gaps / step
        steps = np.round(ratio)
        # evenly spaced, allowing a sign that did not come out (thin signs break up in a blurry capture)
        if (steps < 1).any() or (np.abs(ratio - steps) > 0.2).any() or 1 + int(steps.sum()) != 12:
            continue
        mw, mh = int(np.median([c[2] for c in g])), int(np.median([c[3] for c in g]))
        my = int(np.median([c[1] for c in g]))
        boxes = [g[0]]
        for c, k in zip(g[1:], steps):
            for j in range(1, int(k)):  # fill the missing slot(s)
                cx = xs[0] + (len(boxes)) * step
                boxes.append((int(cx - mw / 2), my, mw, mh))
            boxes.append(c)
        out.boxes = [tuple(map(int, c)) for c in boxes]
        break
    if len(out.boxes) != 12:
        return out
    out.found = True
    gh = int(np.median([b[3] for b in out.boxes]))
    lit = 0
    for x, y, bw, bh in out.boxes:
        cx = x + bw // 2
        sy0, sy1 = y + bh + int(0.6 * gh), y + bh + int(2.4 * gh)
        box = light[max(0, sy0):min(h, sy1), max(0, cx - gh // 2):cx + gh // 2]
        if box.size and float(box.mean()) > 0.25:
            lit += 1
        else:
            break
    out.lit = lit
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    out.templates = [gray[max(0, y - 2):y + bh + 2, max(0, x - 2):x + bw + 2].copy() for x, y, bw, bh in out.boxes]
    return out


def _merge_slots(g: list[tuple]) -> list[tuple]:
    """Join pieces of one sign (some signs are drawn as two separate shapes) into one box."""
    if len(g) < 3:
        return g
    xs = [c[0] + c[2] / 2 for c in g]
    step = float(np.median(np.diff(xs)))
    out = [list(g[0])]
    for c in g[1:]:
        p = out[-1]
        if (c[0] + c[2] / 2) - (p[0] + p[2] / 2) < 0.45 * step:
            x0, y0 = min(p[0], c[0]), min(p[1], c[1])
            x1, y1 = max(p[0] + p[2], c[0] + c[2]), max(p[1] + p[3], c[1] + c[3])
            out[-1] = [x0, y0, x1 - x0, y1 - y0]
        else:
            out.append(list(c))
    return [tuple(c) for c in out]


def _edges(gray: np.ndarray) -> np.ndarray:
    e = cv2.Canny(gray, 40, 120)
    return cv2.GaussianBlur(e.astype(np.float32), (5, 5), 0)


def find_on_strip(strip: np.ndarray, template: np.ndarray, scales=(1.5, 1.65, 1.8, 1.95, 2.1, 2.3)) -> StripHit | None:
    """Best place for ``template`` (a top-row sign, grey) on the strip crop (BGR), by edge shape."""
    if strip is None or template is None or template.size == 0:
        return None
    se = _edges(cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY))
    best: StripHit | None = None
    for s in scales:
        t = cv2.resize(template, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR)
        if t.shape[0] >= se.shape[0] or t.shape[1] >= se.shape[1]:
            continue
        te = _edges(t)
        if te.max() <= 0:
            continue
        res = cv2.matchTemplate(se, te, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if best is None or mx > best.score:
            # the best score away from this spot, to judge how clear the match is
            masked = res.copy()
            x0 = max(0, loc[0] - t.shape[1])
            masked[:, x0:loc[0] + t.shape[1]] = -1
            best = StripHit(loc[0] + t.shape[1] / 2, loc[1] + t.shape[0] / 2, float(mx), float(masked.max()))
    return best
