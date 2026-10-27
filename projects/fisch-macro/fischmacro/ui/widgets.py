"""Reusable UI building blocks."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from fischmacro.profiles.schema import field_meta
from fischmacro.ui.theme import C


# --------------------------------------------------------------------------- layout helpers

class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 18, 20, 18)
        self.lay.setSpacing(10)
        if title:
            head = QHBoxLayout()
            t = QLabel(title)
            t.setObjectName("cardTitle")
            head.addWidget(t)
            head.addStretch(1)
            self.head = head
            self.lay.addLayout(head)
            if subtitle:
                s = QLabel(subtitle)
                s.setObjectName("muted")
                s.setWordWrap(True)
                self.lay.addWidget(s)

    def add(self, w):
        if isinstance(w, QWidget):
            self.lay.addWidget(w)
        else:
            self.lay.addLayout(w)
        return w


def page_header(title: str, subtitle: str) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 6)
    v.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("pageTitle")
    s = QLabel(subtitle)
    s.setObjectName("pageSub")
    s.setWordWrap(True)
    v.addWidget(t)
    v.addWidget(s)
    return w


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("hline")
    return f


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def exp_badge() -> QLabel:
    b = QLabel("EXPERIMENTAL")
    b.setObjectName("badgeExp")
    b.setToolTip("Implemented but not verified against every situation in the live game.")
    return b


class StatTile(QFrame):
    def __init__(self, caption: str, value: str = "-", accent: str | None = None):
        super().__init__()
        self.setObjectName("tile")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(2)
        self.cap = label(caption.upper(), "tileLabel")
        self.val = label(value, "tileValue")
        if accent:
            self.val.setStyleSheet(f"color: {accent};")
        self.sub = label("", "faint")
        v.addWidget(self.cap)
        v.addWidget(self.val)
        v.addWidget(self.sub)

    def set(self, value: str, sub: str | None = None, color: str | None = None) -> None:
        self.val.setText(value)
        if sub is not None:
            self.sub.setText(sub)
        if color:
            self.val.setStyleSheet(f"color: {color};")


class StatusDot(QWidget):
    """Small coloured dot with a soft glow; pulses while running."""

    def __init__(self, size: int = 12):
        super().__init__()
        self._color = QColor(C["faint"])
        self._phase = 0.0
        self._pulse = False
        self.setFixedSize(size + 8, size + 8)

    def set_state(self, color: str, pulse: bool) -> None:
        self._color = QColor(color)
        self._pulse = pulse
        self.update()

    def tick(self) -> None:
        if self._pulse:
            self._phase = (self._phase + 0.08) % 1.0
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(4, 4, -4, -4)
        if self._pulse:
            glow = QColor(self._color)
            glow.setAlphaF(0.35 * (1 - self._phase))
            grow = 4 * self._phase
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(r).adjusted(-grow, -grow, grow, grow))
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(r)


# --------------------------------------------------------------------------- images

def bgr_to_pixmap(img: np.ndarray) -> QPixmap:
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    qimg = QImage(img.data, w, h, img.strides[0], QImage.Format_BGR888)
    return QPixmap.fromImage(qimg.copy())


class ImageView(QLabel):
    """Shows a pixmap scaled to fit, keeping aspect ratio."""

    def __init__(self, placeholder: str = "No image"):
        super().__init__(placeholder)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(f"background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 12px; color: {C['faint']};")
        self._pix: QPixmap | None = None

    def set_image(self, img: np.ndarray | None) -> None:
        if img is None:
            self._pix = None
            self.clear()
            return
        self._pix = bgr_to_pixmap(img)
        self._rescale()

    def _rescale(self) -> None:
        if self._pix is not None:
            self.setPixmap(self._pix.scaled(self.size() - QSize(4, 4), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()


class ReelGraph(QWidget):
    """Compact visualisation of the reel tracker: bar, fish, prediction, command."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(92)
        self.data = None
        self.active = False

    def set_data(self, debug, active: bool) -> None:
        self.data = debug
        self.active = active
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        track = QRectF(10, 18, w - 20, 26)
        p.setPen(QPen(QColor(C["border_hi"]), 1))
        p.setBrush(QColor(C["surface"]))
        p.drawRoundedRect(track, 6, 6)
        d = self.data
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        if not self.active or d is None or d.bar_width <= 0:
            p.setPen(QColor(C["faint"]))
            p.drawText(track, Qt.AlignCenter, "Reel minigame not active")
            return
        x = lambda v: track.left() + max(0.0, min(1.0, v)) * track.width()  # noqa: E731
        bl, br = d.bar_center - d.bar_width / 2, d.bar_center + d.bar_width / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 210))
        p.drawRoundedRect(QRectF(x(bl), track.top() + 3, x(br) - x(bl), track.height() - 6), 4, 4)
        p.setPen(QPen(QColor(C["accent"]), 2, Qt.DashLine))
        p.drawLine(int(x(d.predicted)), int(track.top() - 6), int(x(d.predicted)), int(track.bottom() + 6))
        p.setPen(QPen(QColor(C["danger"]), 3))
        p.drawLine(int(x(d.fish_x)), int(track.top() - 4), int(x(d.fish_x)), int(track.bottom() + 4))
        # duty bar
        duty = QRectF(10, track.bottom() + 14, (w - 20) * d.duty, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["primary"]))
        p.drawRoundedRect(duty, 3, 3)
        p.setPen(QColor(C["muted"]))
        p.drawText(QRectF(10, track.bottom() + 24, w - 20, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   f"error {d.error:+.3f}   fish v {d.fish_v:+.2f}/s   duty {d.duty:.0%}   "
                   f"{'HOLD' if d.hold else 'release'}   hover {d.hover:.2f}{' (learned)' if d.hover_learned else ''}"
                   f"   [{d.reason}]")


# --------------------------------------------------------------------------- editors

class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, value: str = "#FFFFFF"):
        super().__init__()
        self.clicked.connect(self._pick)
        self.setMaximumWidth(180)
        self.set_value(value)

    def set_value(self, value: str) -> None:
        self._value = value.upper()
        self.setText(f"  {self._value}")
        pm = QPixmap(36, 36)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 90), 2))
        p.setBrush(QColor(self._value))
        p.drawRoundedRect(QRectF(2, 2, 32, 32), 8, 8)
        p.end()
        pm.setDevicePixelRatio(2)
        self.setIcon(QIcon(pm))
        self.setIconSize(QSize(18, 18))
        self.setStyleSheet("QPushButton { text-align: left; padding-left: 10px; }")

    def value(self) -> str:
        return self._value

    def _pick(self) -> None:
        col = QColorDialog.getColor(QColor(self._value), self, "Pick colour")
        if col.isValid():
            self.set_value(col.name())
            self.changed.emit(self._value)


class KeyEdit(QLineEdit):
    """Text field for a single in-game key name (e.g. '1', 'e', 'enter', '\\\\')."""

    def __init__(self, value: str = ""):
        super().__init__(value)
        self.setPlaceholderText("key name, e.g. 1, e, enter, \\")
        self.setMaximumWidth(180)


class PathEdit(QWidget):
    changed = Signal(str)

    def __init__(self, value: str = "", filt: str = "Images (*.png *.jpg *.bmp)"):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(value)
        self.edit.setPlaceholderText("not set")
        b = QPushButton("Browse")
        b.clicked.connect(self._browse)
        c = QPushButton("Clear")
        c.setObjectName("ghost")
        c.clicked.connect(lambda: self.set_value("", emit=True))
        h.addWidget(self.edit, 1)
        h.addWidget(b)
        h.addWidget(c)
        self.filt = filt
        self.edit.editingFinished.connect(lambda: self.changed.emit(self.edit.text()))

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", self.edit.text(), self.filt)
        if path:
            self.set_value(path, emit=True)

    def set_value(self, v: str, emit: bool = False) -> None:
        self.edit.setText(v)
        if emit:
            self.changed.emit(v)

    def value(self) -> str:
        return self.edit.text()


def _make_editor(kind: str, value: Any, meta: dict, on_change: Callable[[Any], None]) -> QWidget:
    if kind == "bool":
        w = QCheckBox()
        w.setChecked(bool(value))
        w.toggled.connect(on_change)
    elif kind == "choice":
        w = QComboBox()
        w.addItems(meta.get("choices") or [])
        w.setCurrentText(str(value))
        w.currentTextChanged.connect(on_change)
    elif kind == "color":
        w = ColorButton(str(value))
        w.changed.connect(on_change)
    elif kind == "key":
        w = KeyEdit(str(value))
        w.editingFinished.connect(lambda: on_change(w.text().strip()))
    elif kind == "path":
        w = PathEdit(str(value))
        w.changed.connect(on_change)
    elif kind == "int":
        w = QSpinBox()
        w.setRange(int(meta.get("min") if meta.get("min") is not None else -10**6),
                   int(meta.get("max") if meta.get("max") is not None else 10**6))
        w.setValue(int(value))
        if meta.get("suffix"):
            w.setSuffix(meta["suffix"])
        w.valueChanged.connect(on_change)
    elif kind == "float":
        w = QDoubleSpinBox()
        dec = meta.get("decimals") if meta.get("decimals") is not None else 2
        w.setDecimals(dec)
        w.setRange(float(meta.get("min") if meta.get("min") is not None else -1e6),
                   float(meta.get("max") if meta.get("max") is not None else 1e6))
        w.setSingleStep(float(meta.get("step") or 10 ** -dec))
        w.setValue(float(value))
        if meta.get("suffix"):
            w.setSuffix(meta["suffix"])
        w.valueChanged.connect(on_change)
    else:
        w = QLineEdit(str(value))
        w.editingFinished.connect(lambda: on_change(w.text()))
    for sb in (QSpinBox, QDoubleSpinBox):
        if isinstance(w, sb):
            w.setMaximumWidth(180)
            w.setFocusPolicy(Qt.StrongFocus)  # do not change values when scrolling past
    if isinstance(w, QComboBox):
        w.setMaximumWidth(220)
        w.setFocusPolicy(Qt.StrongFocus)
    return w


def _kind_for(value: Any, meta: dict) -> str:
    if meta.get("choices"):
        return "choice"
    if meta.get("kind"):
        return meta["kind"]
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _row_label(text: str, help_text: str, experimental: bool) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    lab = QLabel(text)
    if help_text:
        lab.setToolTip(help_text)
        w.setToolTip(help_text)
    h.addWidget(lab)
    if experimental:
        h.addWidget(exp_badge())
    h.addStretch(1)
    return w


class ConfigForm(QWidget):
    """Editable form generated from a config dataclass's field metadata."""

    changed = Signal(str)

    def __init__(self, target: Any, only: list[str] | None = None, exclude: list[str] | None = None):
        super().__init__()
        self.only, self.exclude = only, exclude or []
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(18)
        self.form.setVerticalSpacing(13)
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.set_target(target)

    def set_target(self, target: Any) -> None:
        self.target = target
        while self.form.rowCount():
            self.form.removeRow(0)
        for name, meta in field_meta(type(target)):
            if (self.only and name not in self.only) or name in self.exclude:
                continue
            value = getattr(target, name)
            kind = _kind_for(value, meta)

            def setter(v, name=name, kind=kind):
                if kind == "int":
                    v = int(v)
                elif kind == "float":
                    v = float(v)
                setattr(self.target, name, v)
                self.changed.emit(name)
            editor = _make_editor(kind, value, meta, setter)
            if meta.get("help"):
                editor.setToolTip(meta["help"])
            self.form.addRow(_row_label(meta["label"], meta.get("help", ""), meta.get("experimental", False)), editor)


class ModuleForm(QWidget):
    """Form for a game module's ``fields`` writing into its settings dict."""

    changed = Signal(str)

    def __init__(self, module):
        super().__init__()
        self.module = module
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(13)
        for f in module.fields:
            meta = {"min": f.min, "max": f.max, "choices": f.choices, "decimals": 2 if f.kind == "float" else None}
            kind = "choice" if f.choices else f.kind

            def setter(v, key=f.key):
                self.module.settings[key] = v
                self.changed.emit(key)
            editor = _make_editor(kind, module.settings.get(f.key, f.default), meta, setter)
            form.addRow(_row_label(f.label, f.help, f.experimental), editor)
