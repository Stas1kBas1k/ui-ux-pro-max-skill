from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from fischmacro.automation.engine import EngineSnapshot, Status
from fischmacro.ui.fancy import CycleTimeline, HeroBanner
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C, EVENT_COLORS, STATE, STATUS_COLORS
from fischmacro.ui.widgets import Card, StatTile, StatusDot, label


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

        self.banner = label("", "banner", wrap=True)
        self.banner.hide()
        root.addWidget(self.banner)
        self.error_banner = label("", "bannerError", wrap=True)
        self.error_banner.hide()
        root.addWidget(self.error_banner)

        # --- tiles
        grid = QGridLayout()
        grid.setSpacing(12)
        self.t_state = StatTile("Automation state", "IDLE", C["primary_hi"])
        self.t_game = StatTile("Detected game state", "-")
        self.t_time = StatTile("Session time", "0:00:00")
        self.t_fps = StatTile("Detection FPS", "-")
        self.t_catch = StatTile("Catches", "0", C["success"])
        self.t_fail = StatTile("Failures", "0", C["danger_hi"])
        self.t_unconf = StatTile("Unconfirmed", "0", C["warning"])
        self.t_rate = StatTile("Catches / hour", "-", C["accent"])
        tiles = [self.t_state, self.t_game, self.t_time, self.t_fps, self.t_catch, self.t_fail, self.t_unconf, self.t_rate]
        for i, t in enumerate(tiles):
            grid.addWidget(t, i // 4, i % 4)
        root.addLayout(grid)

        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)
        conf = Card("Detection confidence", "How sure the vision engine is about what it sees right now.")
        self.conf_bar = QProgressBar()
        self.conf_bar.setRange(0, 100)
        self.conf_bar.setFormat("%p%")
        conf.add(self.conf_bar)
        self.conf_detail = label("", "faint", wrap=True)
        conf.add(self.conf_detail)
        self.held_lbl = label("Held inputs: none", "faint")
        conf.add(self.held_lbl)
        left.addWidget(conf)
        tl = Card("Cycle timeline", "Each bar is one fishing cycle this session; taller bars took longer.")
        self.timeline = CycleTimeline()
        tl.add(self.timeline)
        left.addWidget(tl)
        bottom.addLayout(left, 3)
        act = Card("Recent activity")
        self.activity = QListWidget()
        self.activity.setMinimumHeight(260)
        act.add(self.activity)
        bottom.addWidget(act, 2)
        root.addLayout(bottom, 1)
        self.add_events(list(ctx.activity))  # history survives theme changes

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

        self.t_state.set(s.fsm_state.replace("_", " "))
        self.t_game.set(s.game_state)
        sess = s.session
        running = st in (Status.RUNNING, Status.PAUSED)
        self.t_time.set(fmt_duration(sess.active_seconds) if (running or sess.cycles) else "0:00:00",
                        f"{sess.cycles} cycles, avg {sess.avg_cycle:.1f}s" if sess.cycles else "")
        self.t_catch.set(str(sess.catches), f"{sess.perfect_casts}/{sess.casts} perfect casts" if sess.casts else "")
        self.t_fail.set(str(sess.failures), f"{sess.recoveries} recoveries" if sess.recoveries else "")
        self.t_unconf.set(str(sess.unconfirmed), "calibrate the progress bar" if sess.unconfirmed else "")
        decided = sess.catches + sess.failures
        self.t_rate.set(f"{sess.catches_per_hour:.0f}" if sess.catches_per_hour else "-",
                        f"{sess.catches / decided:.0%} success rate" if decided else "")
        self.t_fps.set(f"{s.fps:.0f}" if st != Status.STOPPED else "-",
                       f"{s.process_ms:.1f} ms per frame" if st != Status.STOPPED else "")
        self.timeline.set_cycles(sess.history)
        obs = s.observation
        if obs is not None and st != Status.STOPPED:
            self.conf_bar.setValue(int(obs.confidence() * 100))
            parts = []
            if obs.reel.ui_present:
                parts.append(f"reel {obs.reel.confidence:.2f}")
            if obs.shake.present:
                parts.append(f"shake targets {len(obs.shake.targets)}")
            if obs.cast.present:
                parts.append(f"cast {obs.cast.fill:.0%}")
            self.conf_detail.setText(", ".join(parts) or "No game element visible right now.")
        else:
            self.conf_bar.setValue(0)
            self.conf_detail.setText("Vision is not running.")
        self.held_lbl.setText("Held inputs: " + (", ".join(s.held_inputs) if s.held_inputs else "none"))
