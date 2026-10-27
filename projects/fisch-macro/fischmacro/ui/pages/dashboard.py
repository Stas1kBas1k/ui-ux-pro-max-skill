from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from fischmacro.automation.engine import EngineSnapshot, Status
from fischmacro.ui.fancy import HeroBanner
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C, EVENT_COLORS, STATE, STATUS_COLORS
from fischmacro.ui.components import RowGroup, StatStrip, section_title
from fischmacro.ui.widgets import StatusDot, label

STEP_NAMES = {"IDLE": "Idle", "CASTING": "Casting", "WAITING_FOR_BITE": "Waiting for a bite", "SHAKE": "Shaking",
              "REELING": "Reeling", "CATCH_CONFIRMED": "Caught - next cast", "RECOVERY": "Recovering",
              "ERROR": "Stopped on an error"}


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def greeting() -> str:
    h = time.localtime().tm_hour
    return "Good morning" if 5 <= h < 12 else "Good afternoon" if h < 18 else "Good evening"


class DashboardPage(QWidget):
    start_requested = Signal()
    pause_requested = Signal()
    stop_requested = Signal()
    risk_requested = Signal()
    preview_requested = Signal()
    calibrate_requested = Signal()
    vision_requested = Signal()
    autocal_requested = Signal()
    fishing_requested = Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        outer.addWidget(sa)
        body = QWidget()
        sa.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        # --- hero with status and controls
        self.hero = HeroBanner(ctx.settings.appearance.show_artwork)
        text = QVBoxLayout()
        text.setSpacing(6)
        self.hero_title = label(f"{greeting()}, angler", "heroTitle")
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.dot = StatusDot(12)
        self.status_lbl = label("Stopped", "heroSub")
        self.status_lbl.setStyleSheet("font-weight: 700; background: transparent;")
        status_row.addWidget(self.dot)
        status_row.addWidget(self.status_lbl)
        status_row.addStretch(1)
        self.status_sub = label("", "heroSub", wrap=True)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chip_profile = label("", "heroChip")
        self.chip_rod = label("", "heroChip")
        self.chip_mode = label("", "heroChip")
        for c in (self.chip_profile, self.chip_rod, self.chip_mode):
            chips.addWidget(c)
        chips.addStretch(1)
        text.addWidget(self.hero_title)
        text.addLayout(status_row)
        text.addWidget(self.status_sub)
        text.addStretch(1)
        text.addLayout(chips)
        self.hero.lay.addLayout(text, 1)
        btns = QVBoxLayout()
        btns.setSpacing(8)
        self.start_btn = QPushButton(icon("play", C["on_primary"]), "  Start fishing")
        self.start_btn.setObjectName("primary")
        self.pause_btn = QPushButton(icon("pause"), "  Pause")
        self.stop_btn = QPushButton(icon("stop", C["danger_hi"]), "  Emergency stop")
        self.stop_btn.setObjectName("danger")
        for b in (self.start_btn, self.pause_btn, self.stop_btn):
            b.setProperty("class", "big")
            b.setMinimumWidth(190)
            b.setCursor(Qt.PointingHandCursor)
            btns.addWidget(b)
        btns.addStretch(1)
        self.hero.lay.addLayout(btns)
        self.start_btn.clicked.connect(self.start_requested)
        self.pause_btn.clicked.connect(self.pause_requested)
        self.stop_btn.clicked.connect(self.stop_requested)
        root.addWidget(self.hero)

        from fischmacro.ui.setup_checklist import SetupChecklist
        self.checklist = SetupChecklist(ctx, {
            "risk": self.risk_requested.emit, "preview": self.preview_requested.emit,
            "calibrate": self.calibrate_requested.emit, "vision": self.vision_requested.emit,
            "autocal": self.autocal_requested.emit,
            "start": self.start_requested.emit, "live": self._use_live_game, "display": self._open_display,
            "fishing": self.fishing_requested.emit,
        })
        root.addWidget(self.checklist)

        self.banner = label("", "banner", wrap=True)
        self.banner.hide()
        root.addWidget(self.banner)
        self.error_banner = label("", "bannerError", wrap=True)
        self.error_banner.hide()
        root.addWidget(self.error_banner)

        # --- session numbers in one strip, then what the macro sees, then the activity log
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(section_title("This session"))
        self.strip = StatStrip([("catches", "Caught"), ("failed", "Escaped"), ("rate", "Per hour"), ("time", "Time")])
        left.addWidget(self.strip)
        left.addSpacing(8)
        left.addWidget(section_title("Right now"))
        g = RowGroup()
        self.v_step = g.add_value("Step", "What the macro is doing")
        self.v_game = g.add_value("Game", "What it sees on screen")
        self.v_track = g.add_value("Fish tracking", "How sure it is about the fish and the bar")
        self.v_input = g.add_value("Holding", "Mouse buttons and keys held right now")
        left.addWidget(g)
        left.addStretch(1)
        bottom.addLayout(left, 3)
        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(section_title("Recent activity"))
        self.activity = QListWidget()
        self.activity.setMinimumHeight(260)
        right.addWidget(self.activity, 1)
        bottom.addLayout(right, 2)
        root.addLayout(bottom, 1)
        self.add_events(list(ctx.activity))  # history survives theme changes

    def _use_live_game(self) -> None:
        self.ctx.saved_capture_mode = None
        self.ctx.settings.capture.mode = "window"
        self.ctx.settings_edited("capture")
        self.ctx.restart_vision_if_idle()

    @staticmethod
    def _open_display() -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl("ms-settings:display"))

    def add_events(self, events) -> None:
        for ts, kind, msg in events:
            if kind in ("shake",):
                continue
            item = QListWidgetItem(f"{time.strftime('%H:%M:%S', time.localtime(ts))}   {msg}")
            item.setForeground(QColor(EVENT_COLORS.get(kind, C["text"])) if kind != "state" else QColor(C["muted"]))
            self.activity.insertItem(0, item)
        while self.activity.count() > 300:
            self.activity.takeItem(self.activity.count() - 1)

    def refresh(self, s: EngineSnapshot) -> None:
        st = s.status
        color = STATUS_COLORS[st.value]
        self.dot.set_state(color, st == Status.RUNNING and not STATE["reduce_motion"])
        self.dot.tick()
        self.status_lbl.setText(st.value.upper())
        self.status_lbl.setStyleSheet(f"font-weight: 800; letter-spacing: 1px; color: {color}; background: transparent;")
        hk = self.ctx.settings.hotkeys
        sub = {
            Status.STOPPED: f"Automation never starts on its own. Press Start or {hk.start.upper()} when Roblox is ready.",
            Status.MONITORING: "Vision is watching the game. No input is being sent.",
            Status.RUNNING: f"Fishing. {hk.pause.upper()} pauses, {hk.stop.upper()} stops immediately.",
            Status.PAUSED: f"Paused - all inputs released. {hk.pause.upper()} resumes.",
        }[st]
        if s.message:
            sub = s.message
        self.status_sub.setText(sub)
        p = self.ctx.profile
        self.chip_profile.setText(f"Profile · {p.name}")
        self.chip_rod.setText(f"Rod · {p.equipment.rod_name}")
        mode = self.ctx.settings.capture.mode
        self.chip_mode.setText(f"Capture · {mode}")
        self.start_btn.setEnabled(st not in (Status.RUNNING, Status.PAUSED))
        self.pause_btn.setEnabled(st in (Status.RUNNING, Status.PAUSED))
        self.pause_btn.setText("  Resume" if st == Status.PAUSED else "  Pause")
        self.pause_btn.setIcon(icon("play" if st == Status.PAUSED else "pause"))
        sim = mode == "simulation"
        self.banner.setVisible(sim)
        if sim:
            self.banner.setText("Simulation mode: the built-in test game is used and no real mouse or keyboard input "
                                "is sent. Switch Capture source to 'window' in Settings to play Fisch.")
        self.error_banner.setVisible(bool(s.last_error))
        self.error_banner.setText(f"Stopped: {s.last_error}" if s.last_error else "")

        self.checklist.refresh(s)
        sess = s.session
        running = st in (Status.RUNNING, Status.PAUSED)
        self.strip.set("catches", str(sess.catches), C["success"])
        self.strip.set("failed", str(sess.failures), C["danger_hi"] if sess.failures else None)
        self.strip.set("rate", f"{sess.catches_per_hour:.0f}" if sess.catches_per_hour else "-")
        self.strip.set("time", fmt_duration(sess.active_seconds) if (running or sess.cycles) else "0:00:00")
        self.v_step.setText(STEP_NAMES.get(s.fsm_state, s.fsm_state.replace("_", " ").title()))
        self.v_game.setText(s.game_state if st != Status.STOPPED else "---")
        obs = s.observation
        if obs is not None and st != Status.STOPPED and obs.reel.ui_present:
            self.v_track.setText(f"{obs.reel.confidence:.0%}" if obs.reel.bar_found else "fish only")
        else:
            self.v_track.setText("---")
        self.v_input.setText(", ".join(s.held_inputs) if s.held_inputs else "nothing")
