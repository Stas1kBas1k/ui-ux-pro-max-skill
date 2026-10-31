"""Setup wizard: eight short steps from a fresh install to a checked, ready-to-fish setup.

Opened from the Dashboard ("Setup wizard"); it never pops up on its own. Every step shows live state
from the engine, so the user sees whether things actually work instead of ticking boxes.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from fischmacro.automation.engine import Status
from fischmacro.game_data import ALL_RODS
from fischmacro.ui.components import DotCombo, SquareCheck
from fischmacro.ui.theme import C

STEPS = ["App setup", "Game preparation", "Rod and skin", "Detection test", "Calibration", "Validation",
         "Manual fallback", "Ready"]
AUTO_ROD = "Automatic (read from screen)"


def _text(t: str) -> QLabel:
    lab = QLabel(t)
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.RichText)
    return lab


class SetupWizard(QDialog):
    def __init__(self, ctx, parent=None, *, set_regions=None, start_fishing=None):
        super().__init__(parent)
        self.ctx = ctx
        self.set_regions = set_regions
        self.start_fishing = start_fishing
        self.setWindowTitle("Setup wizard")
        self.resize(820, 520)
        self.reel_frames = 0
        self.reel_good = 0
        root = QHBoxLayout(self)
        self.steps = QListWidget()
        self.steps.addItems([f"{i + 1}. {s}" for i, s in enumerate(STEPS)])
        self.steps.setFixedWidth(200)
        self.steps.currentRowChanged.connect(self._go)
        root.addWidget(self.steps)
        right = QVBoxLayout()
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        self.live = QLabel("")
        self.live.setWordWrap(True)
        self.live.setStyleSheet(f"color: {C['accent']};")
        right.addWidget(self.live)
        nav = QHBoxLayout()
        self.back = QPushButton("Back")
        self.next = QPushButton("Next")
        self.next.setObjectName("primary")
        self.back.clicked.connect(lambda: self.steps.setCurrentRow(self.steps.currentRow() - 1))
        self.next.clicked.connect(self._next)
        nav.addStretch(1)
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        right.addLayout(nav)
        root.addLayout(right, 1)
        for build in (self._app, self._game, self._rod, self._detect, self._calibrate, self._validate,
                      self._manual, self._ready):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setAlignment(Qt.AlignTop)
            build(v)
            self.stack.addWidget(w)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(400)
        self.steps.setCurrentRow(0)

    # ---------------------------------------------------------------- pages
    def _app(self, v) -> None:
        from fischmacro.paths import data_dir
        v.addWidget(_text("<h2>App setup</h2>Settings, profiles and logs are kept here:<br>"
                          f"<b>{data_dir()}</b><br><br>This macro only looks at the screen and sends normal mouse "
                          "and key input. It does not read game memory or bypass anything. Using macros may be "
                          "against the game's rules - you decide whether to use it."))
        row = QHBoxLayout()
        self.ack = SquareCheck(self.ctx.settings.risk_acknowledged)
        row.addWidget(self.ack)
        row.addWidget(_text("I understand and want to continue"))
        row.addStretch(1)
        v.addLayout(row)

    def _game(self, v) -> None:
        v.addWidget(_text("<h2>Game preparation</h2><ol><li>Open Roblox and join Fisch.</li>"
                          "<li>Keep the default UI scale and do not cover the bottom of the screen.</li>"
                          "<li>Put your rod in a hotbar slot and hold it.</li>"
                          "<li>Stand at water where you can cast.</li></ol>"
                          "The line below shows whether the game window is found."))

    def _rod(self, v) -> None:
        p = self.ctx.profile
        v.addWidget(_text("<h2>Rod and skin</h2>Pick your rod, or let it be read from the screen. Rods with their "
                          "own minigame (Lullaby, Stellarwave, MiguRod, Halibut Harpoon) get matching settings."))
        current = p.equipment.rod_name if p.equipment.rod_name in ALL_RODS else AUTO_ROD
        self.rod = DotCombo([(AUTO_ROD, "#22C55E")] + [(r, None) for r in ALL_RODS], current)
        v.addWidget(self.rod)
        v.addWidget(_text("Skin (optional label - every skin is tracked by shape, colours are not needed):"))
        self.skin = QLineEdit(p.equipment.skin)
        self.skin.setPlaceholderText("e.g. Toothly Interstellar")
        v.addWidget(self.skin)
        self.rod_note = _text("")
        v.addWidget(self.rod_note)

    def _detect(self, v) -> None:
        v.addWidget(_text("<h2>Detection test</h2>Press <b>Watch</b>, then cast and play a reel by hand. The line "
                          "below says what is seen. Fish and bar should be found while the reel is on screen."))
        b = QPushButton("Watch")
        b.clicked.connect(self._watch)
        v.addWidget(b, 0, Qt.AlignLeft)

    def _calibrate(self, v) -> None:
        v.addWidget(_text("<h2>Calibration</h2>Press <b>Calibrate</b>, then play one reel by hand. It takes many "
                          "looks, keeps the ones that agree and checks the result before saving. If it fails it "
                          "says why; nothing changes then."))
        row = QHBoxLayout()
        b = QPushButton("Calibrate")
        b.clicked.connect(lambda: (self._watch(), self.ctx.engine.start_autocalibration()))
        c = QPushButton("Cancel")
        c.clicked.connect(self.ctx.engine.cancel_autocalibration)
        row.addWidget(b)
        row.addWidget(c)
        row.addStretch(1)
        v.addLayout(row)

    def _validate(self, v) -> None:
        v.addWidget(_text("<h2>Validation</h2>Play another reel by hand (or start in <b>Observe only</b> mode, "
                          "which decides but sends no input). The share of reel frames where fish and bar are "
                          "both found is counted below. Aim for 90% or more."))
        row = QHBoxLayout()
        self.observe = SquareCheck(self.ctx.settings.input.observe_only)
        self.observe.toggled.connect(self._set_observe)
        row.addWidget(self.observe)
        row.addWidget(_text("Observe only (no input is sent)"))
        row.addStretch(1)
        v.addLayout(row)
        r = QPushButton("Reset count")
        r.clicked.connect(self._reset_count)
        v.addWidget(r, 0, Qt.AlignLeft)

    def _manual(self, v) -> None:
        v.addWidget(_text("<h2>Manual fallback</h2>If calibration keeps failing, drag the boxes yourself: reel "
                          "bar, progress bar and shake area. Then repeat the validation step."))
        b = QPushButton("Set regions by hand")
        b.clicked.connect(lambda: self.set_regions and self.set_regions())
        v.addWidget(b, 0, Qt.AlignLeft)

    def _ready(self, v) -> None:
        self.summary = _text("")
        v.addWidget(self.summary)
        b = QPushButton("Start fishing")
        b.setObjectName("primary")
        b.clicked.connect(self._start)
        v.addWidget(b, 0, Qt.AlignLeft)

    # ---------------------------------------------------------------- behaviour
    def _watch(self) -> None:
        if self.ctx.engine.status == Status.STOPPED:
            self.ctx.engine.start_vision()

    def _set_observe(self, on: bool) -> None:
        self.ctx.settings.input.observe_only = on
        self.ctx.settings_edited("input")

    def _reset_count(self) -> None:
        self.reel_frames = self.reel_good = 0

    def _apply_rod(self) -> None:
        p = self.ctx.profile
        rod = self.rod.currentText()
        p.equipment.rod_name = "" if rod == AUTO_ROD else rod
        p.equipment.skin = self.skin.text().strip()
        self.ctx.settings.rod_detect.enabled = rod == AUTO_ROD
        if rod != AUTO_ROD:
            from fischmacro.profiles.rod_presets import apply_preset, find_preset
            pre = find_preset(rod)
            if pre is not None:
                apply_preset(p, pre)
                self.rod_note.setText(f"Applied settings for {pre.name}: {pre.note}")
        self.ctx.save_profile()
        self.ctx.settings_edited("rod")

    def _next(self) -> None:
        i = self.steps.currentRow()
        if i == 0:
            if not self.ack.isChecked():
                self.live.setText("Tick the box to continue.")
                return
            self.ctx.settings.risk_acknowledged = True
            self.ctx.save_settings()
        if i == 2:
            self._apply_rod()
        if i == len(STEPS) - 1:
            self.ctx.settings.setup_done = True
            self.ctx.save_settings()
            self.accept()
            return
        self.steps.setCurrentRow(i + 1)

    def _start(self) -> None:
        self.ctx.settings.setup_done = True
        self.ctx.save_settings()
        self.accept()
        if self.start_fishing:
            self.start_fishing()

    def _go(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        self.back.setEnabled(i > 0)
        self.next.setText("Finish" if i == len(STEPS) - 1 else "Next")
        if i == len(STEPS) - 1:
            eng = self.ctx.engine
            rate = f"{self.reel_good / self.reel_frames:.0%}" if self.reel_frames else "not measured"
            self.summary.setText(
                "<h2>Ready</h2><table>"
                f"<tr><td>Rod</td><td>{self.ctx.profile.equipment.rod_name or 'automatic'}</td></tr>"
                f"<tr><td>Rod minigame</td><td>{self.ctx.profile.minigame.kind}</td></tr>"
                f"<tr><td>Calibration</td><td>{eng.autocal_status or 'not run (built-in tracking is used)'}</td></tr>"
                f"<tr><td>Detection in validation</td><td>{rate}</td></tr>"
                f"<tr><td>Input</td><td>{'observe only' if self.ctx.settings.input.observe_only else 'normal'}</td></tr>"
                "</table><br>F6 starts, F7 pauses, F8 stops at any time.")

    def _tick(self) -> None:
        if not self.isVisible():
            return
        i = self.steps.currentRow()
        eng = self.ctx.engine
        s = eng.snapshot()
        if i == 1:
            try:
                src = eng.source or eng._make_source()
                w = src.locate()
                self.live.setText(f"Roblox window found ({w.width} x {w.height})" if w.found else
                                  "Roblox window not found - open the game")
            except Exception as exc:  # noqa: BLE001
                self.live.setText(f"Could not look for the window: {exc}")
        elif i in (3, 5):
            o = s.observation
            if s.status == Status.STOPPED or o is None:
                self.live.setText("Not watching yet" + (" - press Watch" if i == 3 else " - go back and press Watch"))
                return
            r = o.reel
            if r.ui_present:
                self.reel_frames += 1
                self.reel_good += bool(r.fish_found and r.bar_found)
            seen = ("reel: fish " + ("found" if r.fish_found else "NOT found") + ", bar "
                    + ("found" if r.bar_found else "NOT found")) if r.ui_present else \
                ("shake button seen" if o.shake.present else "no reel or shake on screen")
            rate = f" - fish and bar found in {self.reel_good}/{self.reel_frames} reel frames" if self.reel_frames else ""
            self.live.setText(seen + rate)
        elif i == 4:
            self.live.setText(eng.autocal_status or "Not started")
        else:
            self.live.setText("")
