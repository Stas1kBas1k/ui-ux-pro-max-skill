"""Calibration tool: drag rectangles over a frozen screenshot of the game."""
from __future__ import annotations

import copy
import time

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from fischmacro import paths
from fischmacro.profiles.schema import REGION_LABELS, Profile, Region
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import bgr_to_pixmap, label
from fischmacro.vision.frame import bgr_to_hex

REGION_QCOLORS = {
    "reel": "#3B82F6", "progress": "#22D3EE", "shake": "#7C3AED", "cast": "#22C55E",
    "catch_popup": "#FBBF24", "disconnect": "#EF4444", "reconnect_button": "#B4B4B4",
}
COLOR_TARGETS = {
    "fish_color": "Fish indicator", "bar_color": "Catch bar", "progress_color": "Progress fill",
    "shake_color": "Shake button", "cast_color": "Cast power fill", "dialog_color": "Error dialog background",
}
TEMPLATE_TARGETS = {"shake_template": "Shake button template", "catch_template": "Catch popup template"}


def physical_to_logical(left: int, top: int, width: int, height: int) -> QRect | None:
    """Map a physical-pixel screen rect to Qt logical coordinates (per-monitor DPI aware)."""
    for s in QGuiApplication.screens():
        g = s.geometry()
        dpr = s.devicePixelRatio()
        native_w, native_h = g.width() * dpr, g.height() * dpr
        if g.x() <= left < g.x() + native_w and g.y() <= top < g.y() + native_h:
            return QRect(int(g.x() + (left - g.x()) / dpr), int(g.y() + (top - g.y()) / dpr),
                         int(width / dpr), int(height / dpr))
    return None


class CalibrationCanvas(QWidget):
    region_drawn = Signal(str, object)
    color_picked = Signal(str, str)
    template_drawn = Signal(str, object)

    def __init__(self, image: np.ndarray, regions: dict[str, Region]):
        super().__init__()
        self.image = image
        self.pix = bgr_to_pixmap(image)
        self.regions = regions
        self.current = "reel"
        self.mode = "region"            # region | color | template
        self.color_target = "fish_color"
        self.template_target = "shake_template"
        self._drag: tuple[QPointF, QPointF] | None = None
        self._mouse = QPointF(-1, -1)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    # -- geometry
    def _target(self) -> QRectF:
        iw, ih = self.pix.width(), self.pix.height()
        s = min(self.width() / iw, self.height() / ih)
        w, h = iw * s, ih * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _norm(self, p: QPointF) -> tuple[float, float]:
        t = self._target()
        return (min(1.0, max(0.0, (p.x() - t.x()) / t.width())), min(1.0, max(0.0, (p.y() - t.y()) / t.height())))

    def _to_widget(self, r: Region) -> QRectF:
        t = self._target()
        return QRectF(t.x() + r.x * t.width(), t.y() + r.y * t.height(), r.w * t.width(), r.h * t.height())

    # -- events
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.mode == "color":
            nx, ny = self._norm(e.position())
            ih, iw = self.image.shape[:2]
            x, y = min(iw - 1, int(nx * iw)), min(ih - 1, int(ny * ih))
            patch = self.image[max(0, y - 1):y + 2, max(0, x - 1):x + 2].reshape(-1, 3)
            self.color_picked.emit(self.color_target, bgr_to_hex(np.median(patch, axis=0)))
            return
        self._drag = (e.position(), e.position())
        self.update()

    def mouseMoveEvent(self, e):
        self._mouse = e.position()
        if self._drag:
            self._drag = (self._drag[0], e.position())
        self.update()

    def mouseReleaseEvent(self, e):
        if not self._drag or e.button() != Qt.LeftButton:
            return
        (x0, y0), (x1, y1) = self._norm(self._drag[0]), self._norm(self._drag[1])
        self._drag = None
        r = Region(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0), True)
        if r.w < 0.004 or r.h < 0.004:
            self.update()
            return
        if self.mode == "template":
            self.template_drawn.emit(self.template_target, r)
        else:
            self.region_drawn.emit(self.current, r)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#08080B"))
        t = self._target()
        p.drawPixmap(t.toRect(), self.pix)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setPointSizeF(9)
        f.setBold(True)
        p.setFont(f)
        for name, r in self.regions.items():
            if not r.enabled:
                continue
            col = QColor(REGION_QCOLORS.get(name, "#FFFFFF"))
            rect = self._to_widget(r)
            active = name == self.current and self.mode == "region"
            fill = QColor(col)
            fill.setAlpha(55 if active else 18)
            p.setBrush(fill)
            p.setPen(QPen(col, 2.5 if active else 1.2, Qt.SolidLine if active else Qt.DashLine))
            p.drawRect(rect)
            p.setPen(col)
            p.drawText(rect.topLeft() + QPointF(4, -5), REGION_LABELS.get(name, name))
        if self._drag:
            a, b = self._drag
            col = QColor(C["accent"] if self.mode == "template" else REGION_QCOLORS.get(self.current, "#FFF"))
            p.setPen(QPen(col, 2))
            fill = QColor(col)
            fill.setAlpha(60)
            p.setBrush(fill)
            p.drawRect(QRectF(a, b).normalized())
        if self.mode == "color" and t.contains(self._mouse):
            self._draw_loupe(p, t)

    def _draw_loupe(self, p: QPainter, t: QRectF) -> None:
        nx, ny = self._norm(self._mouse)
        ih, iw = self.image.shape[:2]
        x, y = int(nx * iw), int(ny * ih)
        r = 7
        crop = self.image[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1]
        if crop.size == 0:
            return
        big = cv2.resize(crop, (crop.shape[1] * 10, crop.shape[0] * 10), interpolation=cv2.INTER_NEAREST)
        pm = bgr_to_pixmap(big)
        pos = self._mouse + QPointF(24, 24)
        if pos.x() + pm.width() > self.width():
            pos.setX(self._mouse.x() - pm.width() - 24)
        if pos.y() + pm.height() + 26 > self.height():
            pos.setY(self._mouse.y() - pm.height() - 50)
        p.setPen(QPen(QColor("#FFFFFF"), 2))
        p.drawPixmap(pos, pm)
        p.drawRect(QRectF(pos, pm.size().toSizeF()))
        c = pos + QPointF(pm.width() / 2, pm.height() / 2)
        p.drawRect(QRectF(c.x() - 5, c.y() - 5, 10, 10))
        hexv = bgr_to_hex(self.image[min(ih - 1, y), min(iw - 1, x)])
        p.fillRect(QRectF(pos.x(), pos.y() + pm.height(), pm.width(), 22), QColor(0, 0, 0, 200))
        p.drawText(QRectF(pos.x(), pos.y() + pm.height(), pm.width(), 22), Qt.AlignCenter, hexv)


class CalibrationWindow(QWidget):
    closed = Signal(bool)  # True if saved

    def __init__(self, image: np.ndarray, profile: Profile, client_height: int, on_save, game_rect=None):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Fisch Macro - Calibration")
        self.profile = profile
        self.on_save = on_save
        self.image = image
        self.client_height = client_height
        self.regions = copy.deepcopy(profile.regions)
        for n in REGION_LABELS:
            self.regions.setdefault(n, copy.deepcopy(profile.region(n)))
        self.colors: dict[str, str] = {}
        self.templates: dict[str, str] = {}
        self._saved = False

        self.canvas = CalibrationCanvas(image, self.regions)
        self.canvas.region_drawn.connect(self._region_drawn)
        self.canvas.color_picked.connect(self._color_picked)
        self.canvas.template_drawn.connect(self._template_drawn)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self._build_panel()

        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save)
        QShortcut(QKeySequence("H"), self, activated=lambda: self.panel.setVisible(not self.panel.isVisible()))
        for i, name in enumerate(REGION_LABELS):
            QShortcut(QKeySequence(str(i + 1)), self, activated=lambda n=name: self._select(n))

        rect = physical_to_logical(*game_rect) if game_rect else None
        if rect is not None and rect.width() > 200:
            self.setGeometry(rect)
        else:
            avail = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(int(avail.width() * 0.85), int(avail.height() * 0.85))
            self.move(avail.center() - self.rect().center())
            self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)

    # ------------------------------------------------------------------ panel
    def _build_panel(self) -> None:
        panel = QFrame(self)
        panel.setObjectName("card")
        panel.setStyleSheet(f"QFrame#card {{ background: rgba(26,27,34,0.94); border: 1px solid {C['border_hi']}; border-radius: 14px; }}")
        v = QVBoxLayout(panel)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        title = label("Calibration", "cardTitle")
        v.addWidget(title)
        v.addWidget(label("Select a region, then drag a rectangle over that element on the screenshot. "
                          "Keys 1-7 select regions, H hides this panel, Ctrl+S saves, Esc cancels.", "muted", wrap=True))
        self.list = QListWidget()
        self.list.setMaximumHeight(200)
        for name, text in REGION_LABELS.items():
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, name)
            it.setForeground(QColor(REGION_QCOLORS.get(name, "#FFF")))
            self.list.addItem(it)
        self.list.currentItemChanged.connect(lambda cur, _: cur and self._select(cur.data(Qt.UserRole)))
        v.addWidget(self.list)
        self.enabled_chk = QCheckBox("Region enabled")
        self.enabled_chk.toggled.connect(self._toggle_enabled)
        v.addWidget(self.enabled_chk)
        self.coords = label("", "faint", wrap=True)
        v.addWidget(self.coords)

        v.addWidget(label("Colour picker", "cardTitle"))
        h = QHBoxLayout()
        self.color_combo = QComboBox()
        for k, text in COLOR_TARGETS.items():
            self.color_combo.addItem(text, k)
        self.color_combo.currentIndexChanged.connect(lambda _: setattr(self.canvas, "color_target", self.color_combo.currentData()))
        h.addWidget(self.color_combo, 1)
        self.pick_btn = QPushButton(icon("crosshair"), " Pick")
        self.pick_btn.setCheckable(True)
        self.pick_btn.toggled.connect(lambda on: self._set_mode("color" if on else "region"))
        h.addWidget(self.pick_btn)
        v.addLayout(h)
        self.color_lbl = label("", "faint", wrap=True)
        v.addWidget(self.color_lbl)

        v.addWidget(label("Templates (optional)", "cardTitle"))
        h = QHBoxLayout()
        self.tpl_combo = QComboBox()
        for k, text in TEMPLATE_TARGETS.items():
            self.tpl_combo.addItem(text, k)
        self.tpl_combo.currentIndexChanged.connect(lambda _: setattr(self.canvas, "template_target", self.tpl_combo.currentData()))
        h.addWidget(self.tpl_combo, 1)
        self.tpl_btn = QPushButton(icon("camera"), " Capture")
        self.tpl_btn.setCheckable(True)
        self.tpl_btn.toggled.connect(lambda on: self._set_mode("template" if on else "region"))
        h.addWidget(self.tpl_btn)
        v.addLayout(h)
        self.tpl_lbl = label("Drag tightly around one shake button to use template matching instead of colour.",
                             "faint", wrap=True)
        v.addWidget(self.tpl_lbl)

        v.addStretch(1)
        h = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.close)
        save = QPushButton(icon("check", "#FFFFFF"), " Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        h.addWidget(cancel)
        h.addWidget(save)
        v.addLayout(h)
        panel.setFixedWidth(300)
        self.panel = panel
        self.list.setCurrentRow(0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.panel.setFixedHeight(min(self.height() - 24, 760))
        self.panel.move(self.width() - self.panel.width() - 12, 12)
        self.panel.raise_()

    # ------------------------------------------------------------------ actions
    def _set_mode(self, mode: str) -> None:
        self.canvas.mode = mode
        if mode != "color":
            self.pick_btn.blockSignals(True)
            self.pick_btn.setChecked(False)
            self.pick_btn.blockSignals(False)
        if mode != "template":
            self.tpl_btn.blockSignals(True)
            self.tpl_btn.setChecked(False)
            self.tpl_btn.blockSignals(False)
        self.canvas.update()

    def _select(self, name: str) -> None:
        self.canvas.current = name
        self._set_mode("region")
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == name and self.list.currentRow() != i:
                self.list.setCurrentRow(i)
        r = self.regions[name]
        self.enabled_chk.blockSignals(True)
        self.enabled_chk.setChecked(r.enabled)
        self.enabled_chk.blockSignals(False)
        self._show_coords()
        self.canvas.update()

    def _show_coords(self) -> None:
        r = self.regions[self.canvas.current]
        ih, iw = self.image.shape[:2]
        x, y, w, h = r.to_rect(iw, ih)
        self.coords.setText(f"x {r.x:.3f}  y {r.y:.3f}  w {r.w:.3f}  h {r.h:.3f}   ({w}x{h}px @ {iw}x{ih})")

    def _toggle_enabled(self, v: bool) -> None:
        self.regions[self.canvas.current].enabled = v
        self.canvas.update()

    def _region_drawn(self, name: str, r: Region) -> None:
        self.regions[name] = r
        self.enabled_chk.setChecked(True)
        self._show_coords()

    def _color_picked(self, target: str, hexv: str) -> None:
        self.colors[target] = hexv
        self.color_lbl.setText(" · ".join(f"{COLOR_TARGETS[k]}: {v}" for k, v in self.colors.items()))
        self.color_lbl.setStyleSheet(f"color: {C['text']};")

    def _template_drawn(self, target: str, r: Region) -> None:
        ih, iw = self.image.shape[:2]
        x, y, w, h = r.to_rect(iw, ih)
        crop = cv2.cvtColor(self.image[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
        folder = paths.templates_dir() / self.profile.name
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{target.replace('_template', '')}-{time.strftime('%Y%m%d-%H%M%S')}.png"
        cv2.imwrite(str(path), crop)
        self.templates[target] = str(path)
        self.tpl_lbl.setText(f"Saved {TEMPLATE_TARGETS[target].lower()} ({w}x{h}px).")
        self._set_mode("region")

    def _save(self) -> None:
        bad = [REGION_LABELS[n] for n in ("reel",) if not self.regions[n].is_valid()]
        if bad:
            QMessageBox.warning(self, "Calibration", f"Invalid region: {', '.join(bad)}")
            return
        p = self.profile
        p.regions = self.regions
        for k, v in self.colors.items():
            setattr(p.detection, k, v)
        for k, v in self.templates.items():
            setattr(p.detection, k, v)
            setattr(p.detection, f"{k}_ref_h", self.client_height)
        self.on_save()
        self._saved = True
        self.close()

    def closeEvent(self, e):
        super().closeEvent(e)
        self.closed.emit(self._saved)
