from __future__ import annotations

import time

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from fischmacro import paths
from fischmacro.diagnostics.logs import MEMORY
from fischmacro.diagnostics.snapshot import export_diagnostics
from fischmacro.profiles.schema import to_dict
from fischmacro.ui.icons import icon
from fischmacro.ui.pages.dashboard import fmt_duration
from fischmacro.ui.pages.settings import open_folder
from fischmacro.ui.theme import C, EVENT_COLORS
from fischmacro.ui.widgets import Card, StatTile, page_header

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


class LogsPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._log_counter = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(page_header("Logs & Statistics", "Session history, cycle outcomes, recoveries and diagnostic logs."))

        tiles = QGridLayout()
        tiles.setSpacing(12)
        self.t_cycles = StatTile("Total cycles")
        self.t_rate = StatTile("Success rate", accent=C["success"])
        self.t_avg = StatTile("Average cycle")
        self.t_rec = StatTile("Recoveries", accent=C["warning"])
        self.t_err = StatTile("Errors", accent=C["danger_hi"])
        for i, t in enumerate([self.t_cycles, self.t_rate, self.t_avg, self.t_rec, self.t_err]):
            tiles.addWidget(t, 0, i)
        root.addLayout(tiles)

        bar = QHBoxLayout()
        for ic, text, fn in [("download", "Export cycles (CSV)", self._export_csv),
                             ("download", "Export diagnostics (ZIP)", self._export_diag),
                             ("folder", "Open logs folder", lambda: open_folder(paths.logs_dir())),
                             ("trash", "Clear statistics", self._clear)]:
            b = QPushButton(icon(ic), f"  {text}")
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        tabs = QTabWidget()
        self.sessions = QTableWidget(0, 9)
        self.sessions.setHorizontalHeaderLabels(["Started", "Profile", "Duration", "Catches", "Failures",
                                                 "Unconfirmed", "Avg cycle", "Recoveries", "Ended because"])
        self.events = QTableWidget(0, 3)
        self.events.setHorizontalHeaderLabels(["Time", "Kind", "Message"])
        for t in (self.sessions, self.events):
            t.verticalHeader().setVisible(False)
            t.horizontalHeader().setStretchLastSection(True)
            t.setEditTriggers(QTableWidget.NoEditTriggers)
            t.setAlternatingRowColors(True)
        tabs.addTab(self.sessions, "Session history")
        tabs.addTab(self.events, "Recoveries & errors")
        logw = QWidget()
        lv = QVBoxLayout(logw)
        lv.setContentsMargins(0, 8, 0, 0)
        h = QHBoxLayout()
        self.level = QComboBox()
        self.level.addItems(LEVELS)
        self.level.setCurrentText("INFO")
        self.level.currentTextChanged.connect(self._reload_log)
        h.addWidget(self.level)
        h.addStretch(1)
        lv.addLayout(h)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        f = QFont("Consolas")
        f.setStyleHint(QFont.Monospace)
        f.setPointSizeF(9)
        self.log.setFont(f)
        lv.addWidget(self.log)
        tabs.addTab(logw, "Live log")
        card = Card()
        card.add(tabs)
        root.addWidget(card, 1)
        self.refresh_stats()

    def refresh_stats(self) -> None:
        st = self.ctx.stats
        tot = st.totals()
        self.t_cycles.set(str(tot["cycles"]), f"{tot['unconfirmed']} unconfirmed")
        decided = tot["success"] + tot["failure"]
        self.t_rate.set(f"{tot['success'] / decided:.0%}" if decided else "-", f"{tot['success']} caught / {tot['failure']} lost")
        self.t_avg.set(f"{tot['avg_duration']:.1f}s" if tot["cycles"] else "-")
        self.t_rec.set(str(tot["recoveries"]))
        self.t_err.set(str(tot["errors"]))
        rows = st.sessions()
        self.sessions.setRowCount(len(rows))
        for r, s in enumerate(rows):
            dur = (s["ended"] or time.time()) - s["started"]
            vals = [time.strftime("%Y-%m-%d %H:%M", time.localtime(s["started"])),
                    s["profile"] + (" (sim)" if s["simulated"] else ""), fmt_duration(dur), s["catches"], s["failures"],
                    s["unconfirmed"], f"{s['avg_cycle']:.1f}s" if s["avg_cycle"] else "-", s["recoveries"],
                    s["end_reason"] or ("running" if not s["ended"] else "")]
            for c, v in enumerate(vals):
                self.sessions.setItem(r, c, QTableWidgetItem(str(v)))
        self.sessions.resizeColumnsToContents()
        evs = st.recent_events(("recovery", "error", "disconnect", "warning", "detection_error"), 300)
        self.events.setRowCount(len(evs))
        for r, e in enumerate(evs):
            items = [QTableWidgetItem(time.strftime("%m-%d %H:%M:%S", time.localtime(e["ts"]))),
                     QTableWidgetItem(e["kind"]), QTableWidgetItem(e["message"])]
            items[1].setForeground(QColor(EVENT_COLORS.get(e["kind"], C["text"])))
            for c, it in enumerate(items):
                self.events.setItem(r, c, it)
        self.events.resizeColumnsToContents()

    def _reload_log(self) -> None:
        self.log.clear()
        self._log_counter = 0
        self.poll_log()

    def poll_log(self) -> None:
        self._log_counter, recs = MEMORY.since(self._log_counter)
        if not recs:
            return
        min_level = LEVELS.index(self.level.currentText())
        lines = [f"{time.strftime('%H:%M:%S', time.localtime(ts))} {lvl:<7} {name}: {msg}"
                 for ts, lvl, name, msg in recs if lvl in LEVELS and LEVELS.index(lvl) >= min_level]
        if lines:
            self.log.appendPlainText("\n".join(lines))

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export cycles", "fisch-cycles.csv", "CSV (*.csv)")
        if path:
            self.ctx.stats.export_csv(path)

    def _export_diag(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export diagnostics", "fisch-diagnostics.zip", "ZIP (*.zip)")
        if path:
            export_diagnostics(path, to_dict(self.ctx.settings), self.ctx.profile)
            QMessageBox.information(self, "Diagnostics", f"Saved to {path}.\nThe file stays on your PC; share it "
                                                         "only if you choose to.")

    def _clear(self) -> None:
        if QMessageBox.question(self, "Clear statistics", "Delete all stored sessions, cycles and events?") == QMessageBox.Yes:
            self.ctx.stats.clear()
            self.refresh_stats()
