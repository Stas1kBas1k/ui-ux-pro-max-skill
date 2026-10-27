"""Fishing: live status and statistics, then the few choices that matter. Everything else is in 'Advanced'."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCompleter, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from fischmacro.automation.engine import EngineSnapshot, Status
from fischmacro.game_data import ALL_RODS, LULLABY_MODES
from fischmacro.profiles.rod_presets import apply_preset, find_preset
from fischmacro.ui.components import DotCombo, RowGroup, SquareCheck, section_title
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import KeyEdit, page_header

AUTO_ROD = "Automatic (read from screen)"
CAST = [("Normal", "normal", "Short, casual cast right after each catch"),
        ("Perfect", "perfect", "Waits for a full power bar"),
        ("Timed", "timed", "Holds for a fixed time")]
SHAKE = [("Click", "click", "Clicks the shake buttons"), ("Navigation", "navigation", "Uses Roblox UI navigation keys")]
TRACK = [("Standard", "standard", "Follows the fish with the catch bar"),
         ("Precision", "precision", "For tryhard / low-resilience rods with a tiny bar")]
MINI = [("None", "none"), ("Lullaby", "lullaby"), ("Stellarwave", "stellarwave"), ("Targets", "targets")]
MINI_HINT = {"none": "Just the normal catch bar", "lullaby": "Clicks when the pendulum is over a lit section",
             "stellarwave": "Clicks the sign that matches the star", "targets": "Clicks targets as they appear"}
PHASES = {"IDLE": "Idle", "CASTING": "Casting", "WAITING_FOR_BITE": "Waiting for a bite", "SHAKE": "Shaking",
          "REELING": "Reeling", "CATCH_CONFIRMED": "Caught - next cast", "RECOVERY": "Recovering",
          "ERROR": "Stopped on an error"}


def _label_for(options, value) -> str:
    return next((o[0] for o in options if o[1] == value), options[0][0])


def _value_for(options, label) -> str:
    return next((o[1] for o in options if o[0] == label), options[0][1])


class FishingPage(QWidget):
    def __init__(self, ctx, pick_region=None, advanced_factory=None):
        super().__init__()
        self.ctx = ctx
        self.pick_region = pick_region
        self.advanced_factory = advanced_factory
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 0)
        outer.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(page_header("Fishing", "Pick your rod and how to fish. Works with any rod skin - nothing to "
                                              "calibrate first."), 1)
        adv = QPushButton(icon("settings", C["muted"], 16), " Advanced")
        adv.setToolTip("Every number and colour, for fine tuning")
        adv.setCursor(Qt.PointingHandCursor)
        adv.clicked.connect(self.open_advanced)
        head.addWidget(adv, 0, Qt.AlignTop)
        outer.addLayout(head)

        # live status + statistics (built once, refreshed by the window)
        top = QGridLayout()
        top.setHorizontalSpacing(14)
        top.setVerticalSpacing(6)
        top.addWidget(section_title("Status"), 0, 0)
        top.addWidget(section_title("Statistics"), 0, 1)
        st = RowGroup()
        self.v_phase = st.add_value("Phase", icon_name="activity")
        self.v_progress = st.add_value("Progress", icon_name="gauge")
        self.v_input = st.add_value("Input", icon_name="crosshair")
        self.v_rod = st.add_value("Rod", icon_name="rod")
        stats = RowGroup()
        self.v_caught = stats.add_value("Caught", icon_name="fish")
        self.v_lost = stats.add_value("Lost", icon_name="x")
        self.v_rate = stats.add_value("Success rate", icon_name="target")
        self.v_hour = stats.add_value("Per hour", icon_name="clock")
        top.addWidget(st, 1, 0)
        top.addWidget(stats, 1, 1)
        top.setColumnStretch(0, 3)
        top.setColumnStretch(1, 2)
        topw = QWidget()
        topw.setLayout(top)
        topw.setMaximumWidth(1000)
        outer.addWidget(topw)

        self.inner = QWidget()
        self.inner.setMaximumWidth(1000)
        self.col = QVBoxLayout(self.inner)
        self.col.setContentsMargins(0, 4, 10, 24)
        self.col.setSpacing(8)
        wrap = QHBoxLayout()
        wrap.addWidget(self.inner, 10)
        wrap.addStretch(1)
        holder = QWidget()
        holder.setLayout(wrap)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(holder)
        outer.addWidget(sa, 1)
        self.build()

    def _edited(self) -> None:
        self.ctx.profile_edited()

    def build(self) -> None:
        while self.col.count():
            it = self.col.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        p = self.ctx.profile
        st = self.ctx.settings
        m = p.minigame

        self.col.addWidget(section_title("Configuration"))
        g = RowGroup()
        current = AUTO_ROD if st.rod_detect.enabled else (p.equipment.rod_name
                                                          if p.equipment.rod_name in ALL_RODS else AUTO_ROD)
        self.rod_combo = DotCombo([(AUTO_ROD, "#22C55E")] + [(r, None) for r in ALL_RODS], current)
        self.rod_combo.setEditable(True)
        self.rod_combo.setInsertPolicy(DotCombo.NoInsert)
        comp = QCompleter([AUTO_ROD] + ALL_RODS, self.rod_combo)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.rod_combo.setCompleter(comp)
        self.rod_combo.setMinimumWidth(240)
        self.rod_combo.activated.connect(lambda _i: self._choose_rod(self.rod_combo.currentText()))
        hint = "Reads your rod from the screen and loads its settings" if current == AUTO_ROD else \
            (find_preset(current).note if find_preset(current) else "A normal rod - follows the fish")
        g.add_row("Rod", hint, self.rod_combo, "rod")
        if current == AUTO_ROD:
            pick = QPushButton(icon("crosshair", C["muted"], 16), " Pick on screen")
            pick.clicked.connect(self._pick_rod_region)
            g.add_row("Where the rod name shows", "Usually the hotbar tooltip at the bottom", pick, "scan-search")
        track = DotCombo([(o[0], None) for o in TRACK], _label_for(TRACK, p.reel.mode))
        track.currentTextChanged.connect(lambda v: (setattr(p.reel, "mode", _value_for(TRACK, v)), self._edited()))
        g.add_row("Tracking method", next(o[2] for o in TRACK if o[1] == p.reel.mode), track, "crosshair")
        cast = DotCombo([(o[0], None) for o in CAST], _label_for(CAST, p.casting.mode))
        cast.currentTextChanged.connect(lambda v: (setattr(p.casting, "mode", _value_for(CAST, v)), self._edited(),
                                                   self.build()))
        g.add_row("Casting mode", next(o[2] for o in CAST if o[1] == p.casting.mode), cast, "zap")
        shake = DotCombo([(o[0], None) for o in SHAKE], _label_for(SHAKE, p.shake.mode))
        shake.currentTextChanged.connect(lambda v: (setattr(p.shake, "mode", _value_for(SHAKE, v)), self._edited(),
                                                    self.build()))
        g.add_row("Shake mode", next(o[2] for o in SHAKE if o[1] == p.shake.mode), shake, "sparkles")
        if p.shake.mode == "navigation":
            k = KeyEdit(p.shake.nav_toggle_key)
            k.setMaximumWidth(90)
            k.editingFinished.connect(lambda w=k: (setattr(p.shake, "nav_toggle_key", w.text().strip()), self._edited()))
            g.add_row("Navigation key", "Must match 'UI Navigation Toggle' in Roblox settings", k, "keyboard")
        kind = DotCombo([(n, None) for n, _ in MINI], _label_for([(n, v, "") for n, v in MINI], m.kind))
        kind.currentTextChanged.connect(lambda v: (setattr(m, "kind", dict(MINI)[v]), self._edited(), self.build()))
        g.add_row("Rod minigame", MINI_HINT.get(m.kind, ""), kind, "music-4")
        if m.kind == "lullaby":
            modes = DotCombo([("Keep current", None)] + [(n, col) for n, col, _, _ in LULLABY_MODES], m.lullaby_mode)
            buff = next((b for n, _, _, b in LULLABY_MODES if n == m.lullaby_mode), "Leaves the mode as it is")
            modes.currentTextChanged.connect(lambda v: (setattr(m, "lullaby_mode", v), self._edited(), self.build()))
            g.add_row("Lullaby mode", buff, modes, "music-4")
        if m.kind != "none":
            follow = SquareCheck(m.keep_reeling)
            follow.toggled.connect(lambda v: (setattr(m, "keep_reeling", v), self._edited()))
            g.add_row("Also steer the catch bar",
                      "Lullaby: off is best - every click off a lit section costs 5% progress", follow, "fish")
        rk = KeyEdit(p.equipment.rod_slot_key)
        rk.setMaximumWidth(90)
        rk.editingFinished.connect(lambda w=rk: (setattr(p.equipment, "rod_slot_key", w.text().strip() or "1"),
                                                 self._edited()))
        g.add_row("Rod hotbar key", "The key that equips your rod", rk, "keyboard")
        self.col.addWidget(g)

        self.col.addWidget(section_title("While fishing"))
        g = RowGroup()
        mini = SquareCheck(st.mini.shrink_on_start)
        mini.toggled.connect(lambda v: (setattr(st.mini, "shrink_on_start", v), self.ctx.settings_edited("mini")))
        g.add_row("Shrink to a small window", "Shows just the useful numbers while fishing; click to expand",
                  mini, "layers")
        method = DotCombo([("Scan codes (recommended)", None), ("pynput", None)], st.input.method)
        method.currentTextChanged.connect(lambda v: (setattr(st.input, "method", v), self.ctx.settings_edited("input")))
        g.add_row("Input method", "How keys reach Roblox. Takes effect after a restart", method, "keyboard")
        self.col.addWidget(g)
        self.col.addStretch(1)

    def _choose_rod(self, name: str) -> None:
        st = self.ctx.settings
        p = self.ctx.profile
        name = name.strip()
        if name == AUTO_ROD:
            st.rod_detect.enabled = True
            self.ctx.settings_edited("rod")
        elif name:
            st.rod_detect.enabled = False
            self.ctx.settings_edited("rod")
            p.equipment.rod_name = name
            preset = find_preset(name)
            if preset:
                apply_preset(p, preset)
            else:
                # a normal rod: plain reel, no rod minigame
                p.minigame.kind = "none"
            self.ctx.save_profile()
            self.ctx.profile_switched.emit()
            self.ctx.notice.emit("Rod", f"{name}: " + (preset.note if preset else "normal reel settings"))
        self.build()

    def _pick_rod_region(self) -> None:
        if not self.pick_region:
            return
        rd = self.ctx.settings.rod_detect
        r = self.pick_region("Rod name", "Drag a box around the equipped rod's name", rd.region)
        if r is not None:
            rd.region = r
            self.ctx.settings_edited("rod")

    def refresh(self, s: EngineSnapshot) -> None:
        if not self.isVisible():
            return
        running = s.status in (Status.RUNNING, Status.PAUSED)
        self.v_phase.setText(PHASES.get(s.fsm_state, s.fsm_state.title()) if running else "---")
        obs = s.observation
        prog = obs.progress.fill if (obs is not None and obs.progress.present and running) else None
        self.v_progress.setText(f"{prog:.0%}" if prog is not None else "---")
        self.v_input.setText(("Holding" if s.held_inputs else "Released") if running else "---")
        rod = self.ctx.profile.equipment.rod_name
        self.v_rod.setText(self.ctx.engine.detected_rod or (rod if rod and rod != "Any rod" else "---"))
        sess = s.session
        self.v_caught.setText(str(sess.catches))
        self.v_lost.setText(str(sess.failures))
        decided = sess.catches + sess.failures
        self.v_rate.setText(f"{sess.catches / decided:.0%}" if decided else "---")
        self.v_hour.setText(f"{sess.catches_per_hour:.0f}" if sess.catches_per_hour else "---")

    def open_advanced(self) -> None:
        if not self.advanced_factory:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Advanced fishing settings")
        dlg.resize(980, 720)
        v = QVBoxLayout(dlg)
        v.addWidget(self.advanced_factory(), 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        dlg.exec()
        self.build()

    def on_profile_switched(self) -> None:
        self.build()

