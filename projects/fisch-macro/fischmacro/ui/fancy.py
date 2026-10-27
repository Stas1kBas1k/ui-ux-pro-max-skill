"""Richer visual components: artwork hero banner, cycle timeline, toasts, theme cards."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from fischmacro import paths
from fischmacro.ui.theme import C, STATE, THEMES

_PIX: dict[str, QPixmap] = {}


def asset_pixmap(name: str) -> QPixmap | None:
    if name not in _PIX:
        pm = QPixmap(str(paths.resource_path("assets", name)))
        _PIX[name] = pm
    pm = _PIX[name]
    return None if pm.isNull() else pm


class HeroBanner(QFrame):
    """Rounded banner with the rendered underwater artwork behind a theme-coloured gradient."""

    def __init__(self, show_artwork: bool = True):
        super().__init__()
        self.setObjectName("hero")
        self.show_artwork = show_artwork
        self.setMinimumHeight(168)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(26, 20, 22, 20)
        self.lay.setSpacing(12)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.setClipPath(path)
        base = QLinearGradient(r.topLeft(), r.bottomRight())
        base.setColorAt(0, QColor(C["primary"]).darker(260))
        base.setColorAt(1, QColor(C["accent"]).darker(300))
        p.fillRect(r, base)
        pm = asset_pixmap("hero.png") if self.show_artwork else None
        if pm is not None:
            scaled = pm.scaled(int(r.width()), int(r.height()), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(int(r.right() - scaled.width()), int(r.center().y() - scaled.height() / 2), scaled)
        shade = QLinearGradient(r.topLeft(), r.topRight())
        dark = QColor("#05060A")
        for stop, alpha in ((0.0, 0.92), (0.45, 0.70), (1.0, 0.10)):
            col = QColor(dark)
            col.setAlphaF(alpha)
            shade.setColorAt(stop, col)
        p.fillRect(r, shade)
        tint = QColor(C["primary"])
        tint.setAlphaF(0.16)
        p.fillRect(r, tint)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawPath(path)


class CycleTimeline(QWidget):
    """Bars for the most recent cycles: height = duration, colour = outcome."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self.cycles: list[tuple[str, float]] = []

    def set_cycles(self, cycles: list[tuple[str, float]]) -> None:
        if cycles != self.cycles:
            self.cycles = list(cycles)[-48:]
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        f = QFont(self.font())
        f.setPointSizeF(STATE["base_pt"] * 0.85)
        p.setFont(f)
        plot = QRectF(36, 8, w - 44, h - 30)
        p.setPen(QPen(QColor(C["border"]), 1))
        for i in range(3):
            y = plot.top() + plot.height() * i / 2
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        if not self.cycles:
            p.setPen(QColor(C["faint"]))
            p.drawText(plot, Qt.AlignCenter, "Completed cycles will appear here")
            return
        peak = max(5.0, max(d for _, d in self.cycles))
        n = 48
        slot = plot.width() / n
        colors = {"success": C["success"], "failure": C["danger"], "unconfirmed": C["warning"]}
        for i, (outcome, dur) in enumerate(self.cycles):
            bh = max(3.0, plot.height() * dur / peak)
            x = plot.left() + i * slot + slot * 0.18
            grad = QLinearGradient(QPointF(x, plot.bottom() - bh), QPointF(x, plot.bottom()))
            col = QColor(colors.get(outcome, C["muted"]))
            grad.setColorAt(0, col)
            col2 = QColor(col)
            col2.setAlphaF(0.35)
            grad.setColorAt(1, col2)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(x, plot.bottom() - bh, slot * 0.64, bh), 3, 3)
        p.setPen(QColor(C["faint"]))
        p.drawText(QRectF(0, plot.top() - 6, 32, 14), Qt.AlignRight, f"{peak:.0f}s")
        p.drawText(QRectF(0, plot.bottom() - 8, 32, 14), Qt.AlignRight, "0s")
        legend = [("caught", C["success"]), ("lost", C["danger"]), ("unconfirmed", C["warning"])]
        x = plot.left()
        for text, col in legend:
            p.setBrush(QColor(col))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(x, h - 15, 8, 8))
            p.setPen(QColor(C["muted"]))
            p.drawText(QPointF(x + 12, h - 7), text)
            x += 26 + p.fontMetrics().horizontalAdvance(text)


class Toast(QFrame):
    def __init__(self, parent: QWidget, title: str, message: str, color: str, reduce_motion: bool):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setFixedWidth(340)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 14, 0)
        h.setSpacing(12)
        stripe = QFrame()
        stripe.setFixedWidth(5)
        stripe.setStyleSheet(f"background: {color}; border-top-left-radius: 12px; border-bottom-left-radius: 12px;")
        h.addWidget(stripe)
        v = QVBoxLayout()
        v.setContentsMargins(0, 11, 0, 11)
        v.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(f"font-weight: 700; color: {color};")
        m = QLabel(message)
        m.setWordWrap(True)
        m.setStyleSheet(f"color: {C['text']};")
        v.addWidget(t)
        v.addWidget(m)
        h.addLayout(v, 1)
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.reduce_motion = reduce_motion
        self.adjustSize()

    def appear(self) -> None:
        self.show()
        self.raise_()
        if self.reduce_motion:
            self.effect.setOpacity(1.0)
            return
        self._anim = QPropertyAnimation(self.effect, b"opacity", self)
        self._anim.setDuration(220)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def vanish(self, done: Callable[[], None]) -> None:
        if self.reduce_motion:
            done()
            return
        self._anim = QPropertyAnimation(self.effect, b"opacity", self)
        self._anim.setDuration(260)
        self._anim.setStartValue(self.effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(done)
        self._anim.start()


class ToastManager:
    """Stacks toasts in the top-right corner of a host widget."""

    def __init__(self, host: QWidget, max_visible: int = 4):
        self.host = host
        self.max_visible = max_visible
        self.toasts: list[Toast] = []

    def show(self, title: str, message: str, color: str | None = None, ms: int = 4500) -> None:
        toast = Toast(self.host, title, message, color or C["accent"], STATE["reduce_motion"])
        self.toasts.insert(0, toast)
        while len(self.toasts) > self.max_visible:
            self._remove(self.toasts[-1])
        self.reposition()
        toast.appear()
        QTimer.singleShot(ms, lambda: toast in self.toasts and toast.vanish(lambda: self._remove(toast)))

    def _remove(self, toast: Toast) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
        toast.hide()
        toast.deleteLater()
        self.reposition()

    def reposition(self) -> None:
        # Bottom-right, newest at the bottom: never covers the start/stop controls at the top.
        y = self.host.height() - 18
        for t in self.toasts:
            t.adjustSize()
            y -= t.height()
            t.move(self.host.width() - t.width() - 22, y)
            y -= 10


class ThemeCard(QFrame):
    """Clickable preview of a colour theme."""

    clicked = Signal(str)

    def __init__(self, name: str, selected: bool):
        super().__init__()
        self.name = name
        self.setObjectName("themeCard")
        self.setProperty("selected", "true" if selected else "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(170, 112)
        self.palette_ = THEMES[name]
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.addStretch(1)
        lab = QLabel(name + ("  ✓" if selected else ""))
        lab.setStyleSheet("font-weight: 700; background: transparent;")
        v.addWidget(lab)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.name)

    def paintEvent(self, e):
        super().paintEvent(e)
        t = self.palette_
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(12, 12, self.width() - 24, 52)
        p.setPen(QPen(QColor(t["border"]), 1))
        p.setBrush(QColor(t["bg"]))
        p.drawRoundedRect(box, 8, 8)
        p.setBrush(QColor(t["sidebar"]))
        p.drawRoundedRect(QRectF(box.left(), box.top(), 30, box.height()), 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["card"]))
        p.drawRoundedRect(QRectF(box.left() + 38, box.top() + 8, box.width() - 46, 16), 4, 4)
        for i, key in enumerate(("primary", "accent", "success", "danger")):
            p.setBrush(QColor(t[key]))
            p.drawEllipse(QRectF(box.left() + 40 + i * 20, box.top() + 31, 13, 13))
