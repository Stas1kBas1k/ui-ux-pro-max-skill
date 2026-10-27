"""First-run checklist: guides the user from install to the first confirmed catch in Fisch."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from fischmacro.automation.engine import EngineSnapshot
from fischmacro.profiles.schema import DEFAULT_REGIONS, DetectionConfig
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import Card, label


@dataclass
class Step:
    key: str
    title: str
    hint: str
    button: str
    action: Callable[[], None]


class SetupChecklist(Card):
    def __init__(self, ctx, actions: dict[str, Callable[[], None]]):
        super().__init__("Get ready for Fisch", "Six steps from a fresh install to your first automated catch. "
                                                "Progress is detected automatically.")
        self.ctx = ctx
        hide = QPushButton("Hide")
        hide.setObjectName("ghost")
        hide.setToolTip("Hide the checklist (it can be shown again in Settings)")
        hide.clicked.connect(self._dismiss)
        self.head.addWidget(hide)
        top = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setRange(0, 6)
        self.bar.setTextVisible(False)
        self.count = label("", "muted")
        top.addWidget(self.bar, 1)
        top.addWidget(self.count)
        self.add(top)
        self.steps = [
            Step("risk", "Accept the risk notice", "Automation can carry account risk.", "Review", actions["risk"]),
            Step("window", "Find the Roblox window", "Open Fisch windowed or borderless, then start the preview.",
                 "Start preview", actions["preview"]),
            Step("regions", "Calibrate the reel bar", "Auto-calibrate, then fish once - the bar is found by itself.",
                 "Auto-calibrate", actions["autocal"]),
            Step("colors", "Sample the game colours", "Done automatically by auto-calibration (and on rod/skin changes).",
                 "Auto-calibrate", actions["autocal"]),
            Step("reel_seen", "See the minigame in the live preview", "Fish manually and check the reel is tracked.",
                 "Open vision", actions["vision"]),
            Step("first_catch", "Get your first confirmed catch", "Press Start (F6) with Roblox focused.",
                 "Start", actions["start"]),
        ]
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(12)
        self.rows = {}
        for i, st in enumerate(self.steps):
            mark = QLabel()
            mark.setFixedSize(22, 22)
            text = QWidget()
            tl = QHBoxLayout(text)
            tl.setContentsMargins(0, 0, 0, 0)
            tl.setSpacing(10)
            title = label(st.title)
            hint = label(st.hint, "faint")
            tl.addWidget(title)
            tl.addWidget(hint, 1)
            btn = QPushButton(st.button)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(st.action)
            grid.addWidget(mark, i, 0)
            grid.addWidget(text, i, 1)
            grid.addWidget(btn, i, 2)
            self.rows[st.key] = (mark, title, btn)
        grid.setColumnStretch(1, 1)
        self.add(grid)
        self._last = 0.0
        self._real_catches = 0

    def _dismiss(self) -> None:
        self.ctx.settings.setup_dismissed = True
        self.ctx.save_settings()
        self.hide()

    def status(self, snap: EngineSnapshot) -> dict[str, bool]:
        s, p = self.ctx.settings, self.ctx.profile
        prog = s.setup_progress
        live = s.capture.mode != "simulation"
        changed = False
        if live and snap.window_found and snap.status.value != "Stopped" and not prog.get("window"):
            prog["window"] = changed = True
        obs = snap.observation
        if live and obs is not None and obs.reel.present and obs.reel.confidence >= 0.6 and not prog.get("reel_seen"):
            prog["reel_seen"] = changed = True
        if changed:
            self.ctx.save_settings()
        d = DetectionConfig()
        return {
            "risk": s.risk_acknowledged,
            "window": bool(prog.get("window")),
            "regions": p.region("reel") != DEFAULT_REGIONS["reel"],
            "colors": p.detection.fish_color != d.fish_color or p.detection.bar_color != d.bar_color,
            "reel_seen": bool(prog.get("reel_seen")),
            "first_catch": self._real_catches > 0,
        }

    def refresh(self, snap: EngineSnapshot) -> None:
        if self.ctx.settings.setup_dismissed:
            self.hide()
            return
        now = time.monotonic()
        if now - self._last < 1.0:
            return
        self._last = now
        self._real_catches = self.ctx.stats.real_catches()
        done = self.status(snap)
        n = sum(done.values())
        self.bar.setValue(n)
        self.count.setText(f"{n} of {len(done)} done")
        nxt = next((st.key for st in self.steps if not done[st.key]), None)
        for st in self.steps:
            mark, title, btn = self.rows[st.key]
            ok = done[st.key]
            mark.setPixmap(icon("check" if ok else "crosshair" if st.key == nxt else "plus",
                                C["success"] if ok else C["primary_hi"] if st.key == nxt else C["faint"], 20).pixmap(20, 20))
            title.setStyleSheet(f"color: {C['muted'] if ok else C['text']}; font-weight: {600 if st.key == nxt else 400};")
            btn.setVisible(not ok)
            btn.setObjectName("primary" if st.key == nxt else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.setVisible(n < len(done))
