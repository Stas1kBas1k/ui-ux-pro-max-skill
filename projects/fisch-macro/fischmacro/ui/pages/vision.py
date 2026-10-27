from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from fischmacro.automation.engine import EngineSnapshot, Status
from fischmacro.diagnostics.snapshot import annotate
from fischmacro.profiles.schema import REGION_LABELS
from fischmacro.ui.components import RowGroup, section_title
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import Card, ConfigForm, ImageView, ReelGraph, label, page_header


class VisionPage(QWidget):
    calibrate_requested = Signal()
    snapshot_requested = Signal()
    overlay_toggled = Signal(bool)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._last_preview_id = -1
        self._last_preview_t = 0.0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        outer.addWidget(sa)
        body = QWidget()
        sa.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(page_header("Calibration", "Press Auto-calibrate, then catch one fish by hand - the macro finds "
                                                  "the reel bar and its colours by itself. Nothing leaves this PC."), 1)
        adv = QPushButton(icon("settings", C["muted"], 16), " Advanced")
        adv.setToolTip("Screen regions, colours and tolerances")
        adv.clicked.connect(self.open_advanced)
        head.addWidget(adv, 0, Qt.AlignTop)
        root.addLayout(head)

        bar = QHBoxLayout()
        self.preview_btn = QPushButton(icon("vision"), "  Start live preview")
        self.preview_btn.setObjectName("")
        self.preview_btn.clicked.connect(self._toggle_preview)
        self.auto_btn = QPushButton(icon("check", C["on_primary"]), "  Auto-calibrate")
        self.auto_btn.setObjectName("primary")
        self.auto_btn.setToolTip("Watches the screen while you fish once and finds the reel bar and its colours by itself.")
        self.auto_btn.clicked.connect(self._toggle_autocal)
        bar.addWidget(self.auto_btn)
        cal = QPushButton(icon("crosshair"), "  Manual (F10)")
        cal.clicked.connect(self.calibrate_requested)
        snap = QPushButton(icon("camera"), "  Snapshot (F11)")
        snap.clicked.connect(self.snapshot_requested)
        self.overlay_chk = QCheckBox("Overlay (F9)")
        self.overlay_chk.toggled.connect(self.overlay_toggled)
        for w in (self.preview_btn, cal, snap):
            bar.addWidget(w)
        bar.addSpacing(10)
        bar.addWidget(self.overlay_chk)
        bar.addStretch(1)
        root.addLayout(bar)
        self.autocal_lbl = label("", "banner", wrap=True)
        self.autocal_lbl.hide()
        root.addWidget(self.autocal_lbl)

        main = QHBoxLayout()
        main.setSpacing(14)
        left = QVBoxLayout()
        self.view = ImageView("Preview stopped - press 'Start live preview'")
        self.view.setMinimumSize(560, 315)
        left.addWidget(self.view, 1)
        tracker = Card("Reel tracker", "Red: fish. White: catch bar. Purple: how long the mouse is held.")
        self.graph = ReelGraph()
        tracker.add(self.graph)
        row = QHBoxLayout()
        self.hover_lbl = label("Bar balance: learned while reeling.", "faint")
        self.hover_btn = QPushButton(icon("check"), "  Save to profile")
        self.hover_btn.setEnabled(False)
        self.hover_btn.clicked.connect(self._save_hover)
        row.addWidget(self.hover_lbl, 1)
        row.addWidget(self.hover_btn)
        tracker.add(row)
        left.addWidget(tracker)
        main.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(section_title("What it sees"))
        g = RowGroup()
        self._det = {}
        for k, cap, hint in [("window", "Game window", "Roblox must be open"), ("state", "Game state", ""),
                             ("reel", "Reel bar", ""), ("fish", "Fish", ""), ("progress", "Catch progress", ""),
                             ("shake", "Shake buttons", ""), ("cast", "Cast power", ""), ("perf", "Speed", "")]:
            self._det[k] = g.add_value(cap, hint)
        self._det["disc"] = label("")  # error dialog state is shown in the game state row
        right.addWidget(g)
        right.addStretch(1)
        main.addLayout(right, 2)
        root.addLayout(main)

        # advanced: regions and colour tuning, in a dialog
        self.adv_dlg = QDialog(self)
        self.adv_dlg.setWindowTitle("Advanced calibration")
        self.adv_dlg.resize(900, 720)
        dv = QVBoxLayout(self.adv_dlg)
        tabs = QTabWidget()
        dv.addWidget(tabs, 1)
        self.reg_table = QTableWidget(0, 3)
        self.reg_table.setHorizontalHeaderLabels(["Region", "On", "x, y, w, h"])
        self.reg_table.verticalHeader().setVisible(False)
        self.reg_table.horizontalHeader().setStretchLastSection(True)
        self.reg_table.setEditTriggers(QTableWidget.NoEditTriggers)
        tabs.addTab(self.reg_table, "Screen regions")
        self.form = ConfigForm(ctx.profile.detection)
        self.form.changed.connect(ctx.profile_edited)
        fs = QScrollArea()
        fs.setWidgetResizable(True)
        fs.setWidget(self.form)
        tabs.addTab(fs, "Colours && tolerances")
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.adv_dlg.reject)
        dv.addWidget(bb)
        self.refresh_regions()

    # ------------------------------------------------------------------
    def _toggle_preview(self) -> None:
        eng = self.ctx.engine
        if eng.status == Status.STOPPED:
            eng.start_vision()
        elif eng.status == Status.MONITORING:
            eng.stop_vision()
            self.view.set_image(None)
            self.view.setText("Preview stopped")

    def open_advanced(self) -> None:
        self.refresh_regions()
        self.adv_dlg.exec()

    def refresh_regions(self) -> None:
        p = self.ctx.profile
        names = list(REGION_LABELS)
        self.reg_table.setRowCount(len(names))
        for row, n in enumerate(names):
            r = p.region(n)
            self.reg_table.setItem(row, 0, QTableWidgetItem(REGION_LABELS[n]))
            chk = QCheckBox()
            chk.setChecked(r.enabled)
            chk.toggled.connect(lambda v, n=n: self._toggle_region(n, v))
            self.reg_table.setCellWidget(row, 1, chk)
            self.reg_table.setItem(row, 2, QTableWidgetItem(f"{r.x:.3f}, {r.y:.3f}, {r.w:.3f}, {r.h:.3f}"))
        self.reg_table.resizeColumnsToContents()

    def _save_hover(self) -> None:
        learned = self.ctx.engine.fsm.reel.hover.value
        if learned is not None:
            self.ctx.profile.reel.hold_bias = round(learned, 2)
            self.ctx.save_profile()
            self.hover_lbl.setText(f"Saved hover duty {learned:.2f} to profile '{self.ctx.profile.name}'.")

    def _toggle_region(self, name: str, value: bool) -> None:
        self.ctx.profile.region(name).enabled = value
        self.ctx.profile_edited()

    def on_profile_switched(self) -> None:
        self.form.set_target(self.ctx.profile.detection)
        self.refresh_regions()

    def _toggle_autocal(self) -> None:
        eng = self.ctx.engine
        if eng.autocalibrating:
            eng.cancel_autocalibration()
        else:
            eng.start_autocalibration()

    def refresh(self, s: EngineSnapshot, visible: bool) -> None:
        eng = self.ctx.engine
        self.auto_btn.setText("  Cancel auto-calibration" if eng.autocalibrating else "  Auto-calibrate")
        self.autocal_lbl.setVisible(bool(eng.autocal_status))
        self.autocal_lbl.setText(eng.autocal_status)
        st = s.status
        self.preview_btn.setText("  Stop live preview" if st == Status.MONITORING else "  Start live preview")
        self.preview_btn.setEnabled(st in (Status.STOPPED, Status.MONITORING))
        if not visible:
            return
        obs = s.observation
        d = self._det
        if st == Status.STOPPED:
            for v in d.values():
                v.setText("---")
                v.setStyleSheet("")
            self.graph.set_data(None, False)
            return
        ok, bad = C["success"], C["danger"]
        d["window"].setText("Simulation" if s.simulated else
                            ("Found, focused" if s.window_focused else "Found, click into it") if s.window_found
                            else "Not found")
        d["window"].setStyleSheet(f"color: {ok if s.window_found and (s.window_focused or s.simulated) else bad};")
        d["state"].setText(s.game_state)
        if obs is not None:
            r = obs.reel
            d["state"].setText("Error dialog on screen" if obs.disconnect.detected else s.game_state)
            d["reel"].setText(("Seen" if r.bar_found else "Seen (bar unclear)") if r.ui_present else "Not seen")
            d["fish"].setText(f"Tracked at {r.fish_x:.0%}" if r.fish_found and r.ui_present else "---")
            d["progress"].setText(f"{obs.progress.fill:.0%}" if obs.progress.present else "---")
            d["shake"].setText(str(len(obs.shake.targets)) if obs.shake.targets else "none")
            d["cast"].setText(f"{obs.cast.fill:.0%}" if obs.cast.present else "---")
            self.graph.set_data(s.reel if st == Status.RUNNING else None, r.present and st == Status.RUNNING)
        learned = self.ctx.engine.fsm.reel.hover.value
        self.hover_btn.setEnabled(learned is not None)
        if learned is not None and not self.hover_lbl.text().startswith("Saved"):
            self.hover_lbl.setText(f"Bar balance learned: {learned:.2f} (profile has {self.ctx.profile.reel.hold_bias:.2f})")
        d["perf"].setText(f"{s.fps:.0f} fps")

        now = time.monotonic()
        interval = 1.0 / max(1, self.ctx.settings.performance.preview_fps)
        if s.preview is not None and s.frame_id != self._last_preview_id and now - self._last_preview_t >= interval:
            self._last_preview_id = s.frame_id
            self._last_preview_t = now
            frame = s.preview
            scale = min(1.0, 960 / max(1, frame.client_size[0]))
            self.view.set_image(annotate(frame, self.ctx.profile, s.preview_obs, scale))
