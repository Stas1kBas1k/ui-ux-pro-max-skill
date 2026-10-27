"""Click-through debug overlay drawn on top of the game window.

On Windows 10 2004+ the overlay excludes itself from screen capture
(SetWindowDisplayAffinity / WDA_EXCLUDEFROMCAPTURE), so its markers never
reach the detectors. Where that is unavailable it only draws a compact HUD in
a corner that no default detection region covers.
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from fischmacro.automation.engine import EngineSnapshot
from fischmacro.profiles.schema import REGION_LABELS, Profile
from fischmacro.ui.calibration import REGION_QCOLORS, physical_to_logical
from fischmacro.ui.theme import C, STATUS_COLORS

log = logging.getLogger(__name__)


class DebugOverlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.snap: EngineSnapshot | None = None
        self.profile: Profile | None = None
        self.capture_excluded = False

    def showEvent(self, e):
        super().showEvent(e)
        self.capture_excluded = self._exclude_from_capture()

    def _exclude_from_capture(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            ok = ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x11)
            return bool(ok)
        except Exception as exc:  # noqa: BLE001
            log.info("Overlay capture exclusion unavailable: %s", exc)
            return False

    def update_state(self, snap: EngineSnapshot, profile: Profile, game_rect) -> None:
        self.snap, self.profile = snap, profile
        rect = physical_to_logical(*game_rect) if game_rect and not snap.simulated else None
        if rect is None:
            # No real game window: show the HUD in the bottom-left of the primary screen.
            avail = QGuiApplication.primaryScreen().availableGeometry()
            rect = QRect(avail.left() + 20, avail.bottom() - 200, 340, 180)
            self._hud_only = True
        else:
            self._hud_only = not self.capture_excluded
        if self.geometry() != rect:
            self.setGeometry(rect)
        self.update()

    def paintEvent(self, _):
        s, p_ = self.snap, self.profile
        if s is None or p_ is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        f = QFont(self.font())
        f.setPointSizeF(9)
        p.setFont(f)
        if not getattr(self, "_hud_only", True):
            obs = s.observation
            for name, r in p_.regions.items():
                if not r.enabled:
                    continue
                col = QColor(REGION_QCOLORS.get(name, "#FFFFFF"))
                col.setAlpha(150)
                p.setPen(QPen(col, 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                rr = QRectF(r.x * w, r.y * h, r.w * w, r.h * h)
                p.drawRect(rr)
                p.drawText(rr.topLeft() + QPointF(3, -3), REGION_LABELS.get(name, name))
            if obs is not None:
                reel = p_.region("reel")
                rx, ry, rw, rh = reel.x * w, reel.y * h, reel.w * w, reel.h * h
                if obs.reel.ui_present:
                    p.setPen(QPen(QColor(255, 255, 255), 2))
                    p.drawRect(QRectF(rx + obs.reel.bar_left * rw, ry - 4, obs.reel.bar_width * rw, rh + 8))
                if obs.reel.fish_found:
                    p.setPen(QPen(QColor(C["danger"]), 3))
                    fx = rx + obs.reel.fish_x * rw
                    p.drawLine(QPointF(fx, ry - 10), QPointF(fx, ry + rh + 10))
                if s.reel and obs.reel.present:
                    p.setPen(QPen(QColor(C["accent"]), 2, Qt.DashLine))
                    px = rx + s.reel.predicted * rw
                    p.drawLine(QPointF(px, ry - 14), QPointF(px, ry + rh + 14))
                for t in obs.shake.targets:
                    p.setPen(QPen(QColor("#FACC15"), 2))
                    p.drawRect(QRectF((t.x - t.w / 2) * w, (t.y - t.h / 2) * h, t.w * w, t.h * h))
        # HUD panel
        hud_w, hud_h = 320, 150
        hx, hy = 10, h - hud_h - 10
        p.setPen(QPen(QColor(C["border_hi"]), 1))
        p.setBrush(QColor(17, 18, 22, 215))
        p.drawRoundedRect(QRectF(hx, hy, hud_w, hud_h), 10, 10)
        status_col = QColor(STATUS_COLORS.get(s.status.value, C["text"]))
        p.setPen(status_col)
        bold = QFont(f)
        bold.setBold(True)
        bold.setPointSizeF(10.5)
        p.setFont(bold)
        p.drawText(QPointF(hx + 12, hy + 22), f"{s.status.value}  ·  {s.fsm_state.replace('_', ' ')}")
        p.setFont(f)
        p.setPen(QColor(C["text"]))
        obs = s.observation
        lines = [f"Game: {s.game_state}",
                 f"Confidence: {obs.confidence():.2f}" if obs else "Confidence: -",
                 f"FPS {s.fps:.0f}   vision {s.process_ms:.1f} ms",
                 f"Error {s.reel.error:+.3f}   duty {s.reel.duty:.0%}   {'HOLD' if s.reel.hold else 'release'}"
                 if obs is not None and obs.reel.present else "Reel: inactive",
                 f"Catches {s.session.catches}   fails {s.session.failures}   held: {', '.join(s.held_inputs) or 'none'}"]
        if s.message or s.last_error:
            lines.append(s.message or s.last_error)
        for i, line in enumerate(lines):
            p.drawText(QPointF(hx + 12, hy + 44 + i * 18), line[:52])
