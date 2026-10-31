"""Setup & tests: the manual actions a normal user needs, in plain groups with live feedback.

Technical tools (region editor details, colour pickers, templates) stay on Settings -> Vision.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from fischmacro.automation.engine import Status
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import label, page_header


class ActionCard(QFrame):
    def __init__(self, ic: str, title: str, text: str):
        super().__init__()
        self.setObjectName("actionCard")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(8)
        head = QHBoxLayout()
        i = QLabel()
        i.setPixmap(icon(ic, C["primary_hi"], 22).pixmap(22, 22))
        head.addWidget(i)
        head.addWidget(label(title, "cardTitle"), 1)
        v.addLayout(head)
        v.addWidget(label(text, "muted", wrap=True))
        self.status = label("", "rowHint", wrap=True)
        v.addWidget(self.status)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        v.addStretch(1)
        v.addLayout(self.buttons)

    def button(self, text: str, slot, primary: bool = False, ic: str | None = None) -> QPushButton:
        b = QPushButton(icon(ic, C["on_primary"] if primary else C["muted"], 16) if ic else icon("check", "#0000"),
                        ("  " if ic else "") + text)
        if primary:
            b.setObjectName("primary")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        self.buttons.addWidget(b)
        return b


class SetupPage(QWidget):
    library_requested = Signal()
    wizard_requested = Signal()
    regions_requested = Signal()
    overlay_requested = Signal()
    _sim_done = Signal(str)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        outer.addWidget(sa)
        body = QWidget()
        sa.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(4, 12, 12, 12)
        root.setSpacing(14)
        root.addWidget(page_header("Setup & tests", "Everything you may need to do by hand, in order. Most people "
                                                    "only need the first two."))
        grid = QGridLayout()
        grid.setSpacing(14)
        self.rod = ActionCard("rod", "1  Rod and skin", "Pick the rod you are holding and its skin. Its own settings "
                                                         "load automatically.")
        self.rod.button("Open Rod Library", self.library_requested.emit, True, "fish")
        self.cal = ActionCard("crosshair", "2  Calibration", "Finds the reel on your screen while you play one catch "
                                                             "by hand. Nothing changes unless it checks out.")
        self.cal_btn = self.cal.button("Calibrate", self._calibrate, True, "crosshair")
        self.cal.button("Set by hand", self.regions_requested.emit, False, "edit")
        self.det = ActionCard("vision", "3  Test detection", "Watch what the macro sees, without pressing anything. "
                                                             "Cast and reel by hand and check the line below.")
        self.det.button("Watch the game", self._watch, False, "vision")
        self.det.button("Overlay", self.overlay_requested.emit, False, "overlay")
        self.mini = ActionCard("minigame", "4  Test the rod minigame", "Runs this rod's minigame in the built-in test "
                                                                      "game (no Roblox needed, no real input).")
        self.mini_btn = self.mini.button("Run test", self._test_minigame, False, "play")
        self.reset = ActionCard("reset", "5  Reset", "Back to the recommended settings for this rod. Calibration "
                                                     "of your screen is kept.")
        self.reset.button("Reset this rod", self._reset_rod, False, "reset")
        self.wiz = ActionCard("dashboard", "Guided setup", "Eight short steps from a fresh install to fishing.")
        self.wiz.button("Open setup wizard", self.wizard_requested.emit, False, "play")
        for i, c in enumerate((self.rod, self.cal, self.det, self.mini, self.reset, self.wiz)):
            grid.addWidget(c, i // 2, i % 2)
        root.addLayout(grid)
        root.addStretch(1)
        self._sim_done.connect(self._show_sim)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(400)
        self.refresh()

    # -- actions
    def _calibrate(self) -> None:
        eng = self.ctx.engine
        if eng.autocalibrating:
            eng.cancel_autocalibration()
        else:
            eng.start_autocalibration()

    def _watch(self) -> None:
        if self.ctx.engine.status == Status.STOPPED:
            self.ctx.engine.start_vision()

    def _reset_rod(self) -> None:
        from fischmacro.profiles.library import RodLibrary
        p = self.ctx.profile
        rod = p.equipment.rod_name or "Any rod"
        lib = RodLibrary(self.ctx.profiles, self.ctx.settings.library)
        fresh = lib.recommended(rod, p.equipment.skin or "Default", p)
        fresh.name = p.name
        fresh.regions = p.regions  # keep the screen calibration
        fresh.equipment.rod_name = p.equipment.rod_name
        if self.ctx.engine.status in (Status.RUNNING, Status.PAUSED):
            self.reset.status.setText("Stop fishing first")
            return
        self.ctx.profiles.save(fresh)
        self.ctx._use_profile(fresh)
        self.reset.status.setText(f"'{p.name}' is back to the recommended settings")

    def _test_minigame(self) -> None:
        kind = self.ctx.profile.minigame.kind
        self.mini_btn.setEnabled(False)
        self.mini.status.setText("Running 3 catches in the test game...")
        profile = self.ctx.profile

        def work():
            import copy

            from fischmacro.simulation.game import SimulatedFischGame
            from fischmacro.simulation.harness import run_simulation
            try:
                p = copy.deepcopy(profile)
                p.regions = copy.deepcopy(type(p)().regions)  # the test game has its own screen layout
                p.detection = type(p.detection)()
                g = SimulatedFischGame(seed=7, difficulty=0.4)
                if kind != "none":
                    g.rod_minigame = kind
                    g.mini_action = p.minigame.migu_key if kind == "migu" else (p.minigame.action or "click")
                    if kind == "migu":
                        g.progress_gain = 0.05
                res = run_simulation(p, game=g, cycles=3, max_time=240, fps=40)
                ok = res.outcomes.get("success", 0)
                msg = f"{ok}/3 caught in the test game"
                if kind != "none":
                    msg += f" · rod minigame: {g.stats.mini_hits} hit, {g.stats.mini_misses} missed"
            except Exception as exc:  # noqa: BLE001
                msg = f"Test failed to run: {exc}"
            self._sim_done.emit(msg)
        threading.Thread(target=work, name="minigame-test", daemon=True).start()

    def _show_sim(self, msg: str) -> None:
        self.mini_btn.setEnabled(True)
        self.mini.status.setText(msg)

    # -- live state
    def refresh(self) -> None:
        if not self.isVisible():
            return
        eng = self.ctx.engine
        p = self.ctx.profile
        self.rod.status.setText(f"Now: {p.equipment.rod_name or 'not chosen'}"
                                + (f" · {p.equipment.skin}" if p.equipment.skin else "") + f" · profile '{p.name}'")
        self.cal_btn.setText("  Cancel" if eng.autocalibrating else "  Calibrate")
        self.cal.status.setText(eng.autocal_status or "Not run yet - the built-in tracking works without it on most "
                                                      "setups")
        s = eng.snapshot()
        o = s.observation
        if s.status == Status.STOPPED or o is None:
            self.det.status.setText("Not watching")
        elif o.reel.ui_present:
            r = o.reel
            self.det.status.setText(f"Reel seen · fish {'found' if r.fish_found else 'NOT found'} · bar "
                                    f"{'found' if r.bar_found else 'NOT found'} · progress "
                                    f"{f'{o.progress.fill:.0%}' if o.progress.present else '-'}")
        else:
            self.det.status.setText("Shake button seen" if o.shake.present else "Watching - no reel on screen yet")
        if not self.mini.status.text():
            k = p.minigame.kind
            self.mini.status.setText("This rod has no special minigame - the test checks normal reeling"
                                     if k == "none" else f"Rod minigame: {k}")
