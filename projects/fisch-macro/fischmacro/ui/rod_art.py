"""Generated rod artwork for the Rod Library (no game assets are shipped).

Each rod gets a tile with a colour taken from its name, a stylised rod and reel, and a soft glow for rods
with their own minigame, so cards are easy to tell apart at a glance and look the same every time.
"""
from __future__ import annotations

import hashlib

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

_CACHE: dict[tuple, QPixmap] = {}

# a few hand-picked colours for rods with special minigames (match their in-game look)
SPECIAL_HUES = {"lullaby": 205, "stellarwave": 270, "migu": 350, "halibut": 190, "targets": 30}


def rod_hue(name: str, kind: str = "none") -> int:
    if kind in SPECIAL_HUES:
        return SPECIAL_HUES[kind]
    return int(hashlib.md5(name.encode("utf-8")).hexdigest()[:4], 16) % 360


def rod_pixmap(name: str, size: int = 56, kind: str = "none", skin: str = "") -> QPixmap:
    key = (name, size, kind, skin)
    if key in _CACHE:
        return _CACHE[key]
    hue = rod_hue(name + ("|" + skin if skin else ""), kind)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(0, 0, size, size)
    bg = QLinearGradient(r.topLeft(), r.bottomRight())
    bg.setColorAt(0, QColor.fromHsl(hue, 120, 46))
    bg.setColorAt(1, QColor.fromHsl((hue + 40) % 360, 140, 18))
    path = QPainterPath()
    path.addRoundedRect(r, size * 0.24, size * 0.24)
    p.fillPath(path, bg)
    if kind != "none":
        glow = QRadialGradient(QPointF(size * 0.72, size * 0.28), size * 0.6)
        glow.setColorAt(0, QColor(255, 255, 255, 90))
        glow.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, glow)
    # the rod: a slim diagonal with a reel and a line
    pen = QPen(QColor(255, 255, 255, 235), max(2.0, size * 0.055), Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    a, b = QPointF(size * 0.22, size * 0.80), QPointF(size * 0.80, size * 0.20)
    p.drawLine(a, b)
    p.setPen(QPen(QColor(255, 255, 255, 140), max(1.0, size * 0.02)))
    p.drawLine(b, QPointF(size * 0.80, size * 0.62))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 235))
    rr = size * 0.09
    p.drawEllipse(QPointF(size * 0.36, size * 0.66), rr, rr)
    p.setBrush(QColor.fromHsl(hue, 160, 60))
    p.drawEllipse(QPointF(size * 0.80, size * 0.64), size * 0.05, size * 0.05)
    p.end()
    _CACHE[key] = pm
    return pm


def skin_pixmap(rod: str, skin: str, size: int = 44, kind: str = "none") -> QPixmap:
    return rod_pixmap(rod, size, kind, "" if skin == "Default" else skin)
