"""Captured frame container and colour helpers."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from fischmacro.profiles.schema import Region


@dataclass
class Frame:
    """A captured image of (part of) the game client area.

    ``origin`` is where the image's top-left sits inside the client area, so ROI
    captures and full captures are handled identically by detectors.
    """
    image: np.ndarray                       # BGR uint8
    client_size: tuple[int, int]            # (width, height) of the whole client area
    origin: tuple[int, int] = (0, 0)        # image top-left inside the client area
    screen_origin: tuple[int, int] = (0, 0) # client top-left on the virtual screen
    timestamp: float = 0.0
    full: bool = True
    meta: dict = field(default_factory=dict)

    def crop(self, region: Region) -> np.ndarray | None:
        cw, ch = self.client_size
        x, y, w, h = region.to_rect(cw, ch)
        ox, oy = self.origin
        ih, iw = self.image.shape[:2]
        x0, y0 = x - ox, y - oy
        x1, y1 = x0 + w, y0 + h
        if x0 < 0 or y0 < 0 or x1 > iw or y1 > ih:
            # Region not (fully) inside this capture: clip and accept if mostly covered.
            cx0, cy0 = max(0, x0), max(0, y0)
            cx1, cy1 = min(iw, x1), min(ih, y1)
            if cx1 <= cx0 or cy1 <= cy0 or (cx1 - cx0) * (cy1 - cy0) < 0.9 * w * h:
                return None
            return self.image[cy0:cy1, cx0:cx1]
        return self.image[y0:y1, x0:x1]

    def client_to_screen(self, nx: float, ny: float) -> tuple[int, int]:
        cw, ch = self.client_size
        return int(self.screen_origin[0] + nx * cw), int(self.screen_origin[1] + ny * ch)


def hex_to_bgr(color: str) -> tuple[int, int, int]:
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        raise ValueError(f"Invalid colour: {color!r}")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return b, g, r


def bgr_to_hex(bgr) -> str:
    b, g, r = (int(v) for v in bgr[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


def color_mask(image: np.ndarray, color: str, tolerance: int) -> np.ndarray:
    """Binary mask of pixels within ``tolerance`` of ``color`` on every channel."""
    b, g, r = hex_to_bgr(color)
    t = int(tolerance)
    lower = np.array([max(0, b - t), max(0, g - t), max(0, r - t)], dtype=np.uint8)
    upper = np.array([min(255, b + t), min(255, g + t), min(255, r + t)], dtype=np.uint8)
    return cv2.inRange(image, lower, upper)


def union_rect(rects: list[tuple[int, int, int, int]], pad: int, bounds: tuple[int, int]) -> tuple[int, int, int, int]:
    x0 = min(r[0] for r in rects) - pad
    y0 = min(r[1] for r in rects) - pad
    x1 = max(r[0] + r[2] for r in rects) + pad
    y1 = max(r[1] + r[3] for r in rects) + pad
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(bounds[0], x1), min(bounds[1], y1)
    return x0, y0, max(1, x1 - x0), max(1, y1 - y0)
