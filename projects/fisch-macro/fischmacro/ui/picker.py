"""Pick a point or a rectangle on a frozen screenshot of the game (normalised coordinates)."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from fischmacro.profiles.schema import Region
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import bgr_to_pixmap


class _Canvas(QWidget):
    def __init__(self, image: np.ndarray, mode: str, initial):
        super().__init__()
        self.pix = bgr_to_pixmap(image)
        self.mode = mode
        self.value = initial
        self._drag = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setMinimumSize(640, 360)

    def _target(self) -> QRectF:
        iw, ih = self.pix.width(), self.pix.height()
        s = min(self.width() / iw, self.height() / ih)
        return QRectF((self.width() - iw * s) / 2, (self.height() - ih * s) / 2, iw * s, ih * s)

    def _norm(self, p: QPointF) -> tuple[float, float]:
        t = self._target()
        return (min(1.0, max(0.0, (p.x() - t.x()) / t.width())), min(1.0, max(0.0, (p.y() - t.y()) / t.height())))

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.mode == "point":
            self.value = self._norm(e.position())
        else:
            self._drag = (e.position(), e.position())
        self.update()

    def mouseMoveEvent(self, e):
        if self._drag:
            self._drag = (self._drag[0], e.position())
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            (x0, y0), (x1, y1) = self._norm(self._drag[0]), self._norm(self._drag[1])
            self._drag = None
            if abs(x1 - x0) > 0.004 and abs(y1 - y0) > 0.004:
                self.value = Region(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0), True)
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#08080B"))
        t = self._target()
        p.drawPixmap(t.toRect(), self.pix)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(C["accent"])
        p.setPen(QPen(col, 2))
        if self.mode == "point" and self.value:
            x, y = t.x() + self.value[0] * t.width(), t.y() + self.value[1] * t.height()
            p.drawEllipse(QPointF(x, y), 9, 9)
            p.drawLine(QPointF(x - 16, y), QPointF(x + 16, y))
            p.drawLine(QPointF(x, y - 16), QPointF(x, y + 16))
        elif isinstance(self.value, Region):
            r = self.value
            fill = QColor(col)
            fill.setAlpha(50)
            p.setBrush(fill)
            p.drawRect(QRectF(t.x() + r.x * t.width(), t.y() + r.y * t.height(), r.w * t.width(), r.h * t.height()))
        if self._drag:
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(*self._drag[0].toTuple(), 0, 0).united(QRectF(*self._drag[1].toTuple(), 0, 0)))


class ScreenPicker(QDialog):
    """``mode`` is 'point' (returns (x, y)) or 'rect' (returns a Region)."""

    def __init__(self, image: np.ndarray, mode: str, title: str, hint: str, initial=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        lab = QLabel(hint)
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.canvas = _Canvas(image, mode, initial)
        v.addWidget(self.canvas, 1)
        h = QHBoxLayout()
        h.addStretch(1)
        cancel = QPushButton("Cancel")
        ok = QPushButton("Use this")
        ok.setObjectName("primary")
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        h.addWidget(cancel)
        h.addWidget(ok)
        v.addLayout(h)
        avail = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(int(avail.width() * 0.75), int(avail.height() * 0.75))

    @property
    def value(self):
        return self.canvas.value
