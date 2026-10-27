from __future__ import annotations

import copy
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from fischmacro.automation.watchers import PRESET_WATCHERS
from fischmacro.profiles.schema import WATCHER_KINDS, Watcher
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import Card, ConfigForm, label, page_header
from fischmacro.vision.ocr import OcrEngine


class AlertsPage(QWidget):
    def __init__(self, ctx, pick_region=None):
        super().__init__()
        self.ctx = ctx
        self.pick_region = pick_region  # callable(title, hint, initial Region) -> Region | None
        self.current: Watcher | None = None
        self._loading = False
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
        root.addWidget(page_header("Alerts & Watchers", "Read hunts, weather, events and your rod's name from the "
                                                        "screen, then notify you, start routines or pause fishing."))
        self.ocr_banner = label("", "bannerWarn", wrap=True)
        self.ocr_banner.hide()
        root.addWidget(self.ocr_banner)

        row = QHBoxLayout()
        row.setSpacing(14)
        left = Card("Watchers")
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        self.list.currentRowChanged.connect(self._select)
        self.list.itemChanged.connect(self._toggled)
        left.add(self.list)
        g = QHBoxLayout()
        add = QPushButton(icon("plus"), " New")
        add.clicked.connect(lambda: self._add(Watcher("New watcher", enabled=True)))
        preset = QPushButton(icon("copy"), " Preset")
        menu = QMenu(preset)
        for w in PRESET_WATCHERS:
            menu.addAction(w.name, lambda w=w: self._add(copy.deepcopy(w)))
        preset.setMenu(menu)
        rm = QPushButton(icon("trash"), " Delete")
        rm.clicked.connect(self._delete)
        for b in (add, preset, rm):
            g.addWidget(b)
        left.add(g)
        row.addWidget(left, 2)

        self.editor = Card("Watcher")
        f = QFormLayout()
        f.setVerticalSpacing(10)
        self.name = QLineEdit()
        self.enabled = QCheckBox("Enabled")
        self.kind = QComboBox()
        self.kind.addItems(WATCHER_KINDS)
        self.keywords = QLineEdit()
        self.keywords.setPlaceholderText("Megalodon|Great White|Kraken  (empty = any text)")
        self.interval = QDoubleSpinBox()
        self.interval.setMaximumWidth(140)
        self.interval.setRange(0.5, 120)
        self.interval.setSuffix(" s")
        self.cooldown = QDoubleSpinBox()
        self.cooldown.setMaximumWidth(140)
        self.cooldown.setRange(0, 600)
        self.cooldown.setSuffix(" min")
        self.discord = QCheckBox("Send to Discord")
        self.toast = QCheckBox("Show a toast")
        self.pause = QCheckBox("Pause fishing when it matches")
        self.region_lbl = label("", "faint")
        pick = QPushButton(icon("crosshair"), "  Pick region on screen")
        pick.clicked.connect(self._pick)
        rr = QHBoxLayout()
        rr.addWidget(self.region_lbl, 1)
        rr.addWidget(pick)
        for text, w in (("Name", self.name), ("", self.enabled), ("Type", self.kind), ("Keywords", self.keywords),
                        ("Check every", self.interval), ("Re-alert after", self.cooldown), ("", self.discord),
                        ("", self.toast), ("", self.pause)):
            f.addRow(text, w)
        f.addRow("Screen region", rr)
        self.editor.add(f)
        self.note = label("", "muted", wrap=True)
        self.editor.add(self.note)
        self.live = label("", "banner", wrap=True)
        self.editor.add(self.live)
        row.addWidget(self.editor, 4)
        root.addLayout(row)

        for w in (self.name, self.keywords):
            w.editingFinished.connect(self._save)
        for w in (self.enabled, self.discord, self.toast, self.pause):
            w.toggled.connect(self._save)
        self.kind.currentTextChanged.connect(self._save)
        for w in (self.interval, self.cooldown):
            w.valueChanged.connect(self._save)

        dc = Card("Discord", "Get pinged when a hunt starts, the macro stops, or every N catches. Messages go "
                             "only to the webhook you paste here.")
        df = ConfigForm(ctx.settings.notifications, only=["discord_webhook", "discord_mention", "discord_errors",
                                                           "discord_screenshot", "notify_every_catches",
                                                           "auto_profiles"])
        df.changed.connect(ctx.settings_edited)
        dc.add(df)
        h = QHBoxLayout()
        test = QPushButton(icon("check"), "  Send test message")
        test.clicked.connect(self._test_discord)
        h.addWidget(test)
        self.discord_lbl = label("", "faint")
        h.addWidget(self.discord_lbl, 1)
        dc.add(h)
        root.addWidget(dc)
        root.addStretch(1)
        self.reload()

    def reload(self) -> None:
        self._loading = True
        self.list.clear()
        for w in self.ctx.settings.watchers:
            it = QListWidgetItem(f"{w.name}  ·  {w.kind}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if w.enabled else Qt.Unchecked)
            self.list.addItem(it)
        self._loading = False
        self.list.setCurrentRow(0 if self.ctx.settings.watchers else -1)
        if not self.ctx.settings.watchers:
            self._select(-1)

    def _toggled(self, item) -> None:
        if self._loading:
            return
        w = self.ctx.settings.watchers[self.list.row(item)]
        w.enabled = item.checkState() == Qt.Checked
        if self.current is w:
            self.enabled.setChecked(w.enabled)
        self.ctx.save_settings()

    def _add(self, w: Watcher) -> None:
        self.ctx.settings.watchers.append(w)
        self.ctx.save_settings()
        self.reload()
        self.list.setCurrentRow(len(self.ctx.settings.watchers) - 1)

    def _delete(self) -> None:
        if self.current and QMessageBox.question(self, "Watchers", f"Delete '{self.current.name}'?") == QMessageBox.Yes:
            self.ctx.settings.watchers.remove(self.current)
            self.current = None
            self.ctx.save_settings()
            self.reload()

    def _select(self, row: int) -> None:
        ws = self.ctx.settings.watchers
        self.current = ws[row] if 0 <= row < len(ws) else None
        self.editor.setEnabled(self.current is not None)
        if not self.current:
            return
        w = self.current
        self._loading = True
        self.name.setText(w.name)
        self.enabled.setChecked(w.enabled)
        self.kind.setCurrentText(w.kind)
        self.keywords.setText(w.keywords)
        self.interval.setValue(w.interval_s)
        self.cooldown.setValue(w.cooldown_min)
        self.discord.setChecked(w.notify_discord)
        self.toast.setChecked(w.toast)
        self.pause.setChecked(w.pause_automation)
        self.note.setText(w.note)
        self._show_region()
        self._loading = False

    def _show_region(self) -> None:
        r = self.current.region
        self.region_lbl.setText(f"x {r.x:.2f}  y {r.y:.2f}  w {r.w:.2f}  h {r.h:.2f}")

    def _save(self, *_) -> None:
        if self._loading or not self.current:
            return
        w = self.current
        w.name = self.name.text().strip() or w.name
        w.enabled = self.enabled.isChecked()
        w.kind = self.kind.currentText()
        w.keywords = self.keywords.text().strip()
        w.interval_s = self.interval.value()
        w.cooldown_min = self.cooldown.value()
        w.notify_discord = self.discord.isChecked()
        w.toast = self.toast.isChecked()
        w.pause_automation = self.pause.isChecked()
        it = self.list.currentItem()
        if it:
            self._loading = True
            it.setText(f"{w.name}  ·  {w.kind}")
            it.setCheckState(Qt.Checked if w.enabled else Qt.Unchecked)
            self._loading = False
        self.ctx.save_settings()

    def _pick(self) -> None:
        if self.current and self.pick_region:
            r = self.pick_region("Watcher region", "Drag a box around where the text appears (e.g. the hunt "
                                                   "announcement or the rod name).", self.current.region)
            if r is not None:
                self.current.region = r
                self._show_region()
                self.ctx.save_settings()

    def _test_discord(self) -> None:
        n = self.ctx.engine.notifier
        if not n.configured:
            self.discord_lbl.setText("Paste a Discord webhook URL first.")
            return
        n.send("Test message", "Fisch Macro can reach this channel.", key=f"test{time.time()}", min_gap=0)
        self.discord_lbl.setText("Sent - check your Discord channel.")

    def refresh(self) -> None:
        ocr = OcrEngine.shared()
        if ocr.error:
            self.ocr_banner.setText(f"Text recognition is unavailable ({ocr.error}). Watchers are paused.")
        self.ocr_banner.setVisible(bool(ocr.error))
        if not self.current:
            return
        st = self.ctx.engine.watchers.states.get(self.current.name)
        if self.ctx.engine.status.value == "Stopped":
            self.live.setText("Start the live preview or fishing to run watchers.")
        elif st is None or st.last_check < 0:
            self.live.setText("Waiting for the first check..." if self.current.enabled else "Watcher is disabled.")
        else:
            ago = time.monotonic() - st.last_check
            matches = ", ".join(st.matches) if st.matches else "no match"
            self.live.setText(f"Read {ago:.0f}s ago: “{st.text[:120] or '(no text)'}”  →  {matches}")
        if self.ctx.engine.detected_rod and self.current.kind == "rod":
            self.live.setText(self.live.text() + f"\nCurrent rod: {self.ctx.engine.detected_rod}")
        self.live.setStyleSheet(f"color: {C['text']};")
