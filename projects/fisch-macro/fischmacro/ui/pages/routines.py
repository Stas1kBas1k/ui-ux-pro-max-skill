from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from fischmacro.automation.routines import PRESET_ROUTINES
from fischmacro.profiles.schema import STEP_HELP, STEP_KINDS, TRIGGERS, Routine, RoutineStep
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import Card, ConfigForm, exp_badge, label, page_header


def _spin(lo, hi, value, step=1.0, decimals=1) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(value)
    s.setFocusPolicy(Qt.StrongFocus)
    s.setMaximumWidth(140)
    return s


class RoutinesPage(QWidget):
    COLS = ["Step", "Value / item / text", "Seconds", "X", "Y", ""]

    def __init__(self, ctx, pick_point=None):
        super().__init__()
        self.ctx = ctx
        self.pick_point = pick_point  # callable(title, hint, initial) -> (x, y) | None
        self.current: Routine | None = None
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
        root.addWidget(page_header("Routines", "Potions, totems, the Astral Activator, rod recharge and appraising. "
                                               "Routines only run between catches, never during a minigame."))
        row = QHBoxLayout()
        row.setSpacing(14)

        left = Card("Your routines")
        self.list = QListWidget()
        self.list.setMinimumWidth(250)
        self.list.currentRowChanged.connect(self._select)
        self.list.itemChanged.connect(self._toggled)
        left.add(self.list)
        g = QGridLayout()
        add = QPushButton(icon("plus"), " New")
        add.clicked.connect(self._new)
        preset = QPushButton(icon("copy"), " From preset")
        menu = QMenu(preset)
        for r in PRESET_ROUTINES:
            menu.addAction(r.name, lambda r=r: self._add(copy.deepcopy(r)))
        preset.setMenu(menu)
        dup = QPushButton(icon("copy"), " Duplicate")
        dup.clicked.connect(self._dup)
        rm = QPushButton(icon("trash"), " Delete")
        rm.clicked.connect(self._delete)
        for i, b in enumerate((add, preset, dup, rm)):
            g.addWidget(b, i // 2, i % 2)
        left.add(g)
        self.run_btn = QPushButton(icon("play", C["on_primary"]), "  Run now")
        self.run_btn.setObjectName("primary")
        self.run_btn.setToolTip("While fishing: runs after the current catch. Stopped: runs after a 3 s countdown.")
        self.run_btn.clicked.connect(self._run_now)
        left.add(self.run_btn)
        self.run_lbl = label("", "faint", wrap=True)
        left.add(self.run_lbl)
        row.addWidget(left, 2)

        self.editor = Card("Routine")
        self.verify_badge = exp_badge()
        self.verify_badge.setText("VERIFY IN GAME")
        self.editor.head.addWidget(self.verify_badge)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.name = QLineEdit()
        self.enabled = QCheckBox("Enabled")
        self.trigger = QComboBox()
        self.trigger.addItems(TRIGGERS)
        self.interval = _spin(0.1, 1440, 15)
        self.interval.setSuffix(" min")
        self.catches = QSpinBox()
        self.catches.setRange(1, 10000)
        self.catches.setMaximumWidth(140)
        self.watcher = QComboBox()
        self.watcher.setEditable(True)
        self.cooldown = _spin(0, 1440, 1)
        self.cooldown.setSuffix(" min")
        self.repeat_until = QLineEdit()
        self.repeat_until.setPlaceholderText("e.g. Shiny|Sparkling - repeat the steps until one of these is on screen")
        self.max_repeats = QSpinBox()
        self.max_repeats.setRange(1, 500)
        self.max_repeats.setMaximumWidth(140)
        self.reequip = QCheckBox("Re-equip rod at the end")
        self.note = QPlainTextEdit()
        self.note.setMaximumHeight(70)
        for text, w in (("Name", self.name), ("", self.enabled), ("Trigger", self.trigger),
                        ("Every (interval)", self.interval), ("Every N catches", self.catches),
                        ("Watcher (trigger)", self.watcher), ("Cooldown", self.cooldown),
                        ("Repeat until text", self.repeat_until), ("Max repeats", self.max_repeats),
                        ("", self.reequip), ("Notes", self.note)):
            form.addRow(text, w)
        self.editor.add(form)
        self.editor.add(label("Steps", "cardTitle"))
        self.steps = QTableWidget(0, len(self.COLS))
        self.steps.setHorizontalHeaderLabels(self.COLS)
        self.steps.verticalHeader().setVisible(False)
        self.steps.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.steps.setColumnWidth(0, 190)
        for col in (2, 3, 4):
            self.steps.setColumnWidth(col, 110)
        self.steps.setColumnWidth(5, 48)
        self.steps.setMinimumHeight(220)
        self.editor.add(self.steps)
        sb = QHBoxLayout()
        for text, ic, fn in (("Add step", "plus", self._add_step), ("Remove", "trash", self._remove_step),
                             ("Up", "upload", lambda: self._move_step(-1)), ("Down", "download", lambda: self._move_step(1))):
            b = QPushButton(icon(ic), f" {text}")
            b.clicked.connect(fn)
            sb.addWidget(b)
        sb.addStretch(1)
        self.editor.add(sb)
        row.addWidget(self.editor, 5)
        root.addLayout(row)

        for w in (self.name, self.repeat_until):
            w.editingFinished.connect(self._save_fields)
        self.watcher.currentTextChanged.connect(self._save_fields)
        self.enabled.toggled.connect(self._save_fields)
        self.reequip.toggled.connect(self._save_fields)
        self.trigger.currentTextChanged.connect(self._save_fields)
        for w in (self.interval, self.cooldown):
            w.valueChanged.connect(self._save_fields)
        for w in (self.catches, self.max_repeats):
            w.valueChanged.connect(self._save_fields)
        self.note.textChanged.connect(self._save_fields)

        # loadout
        lo = Card("Loadout", "Which item is in which hotbar slot. Items that are not on the hotbar are found by "
                             "typing their name into the inventory search.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.slot_edits = {}
        for i in range(1, 10):
            e = QLineEdit(ctx.settings.loadout.slots.get(str(i), ""))
            e.setPlaceholderText("empty")
            e.editingFinished.connect(lambda i=i, e=e: self._set_slot(i, e.text()))
            grid.addWidget(label(f"Slot {i}", "muted"), (i - 1) // 3, ((i - 1) % 3) * 2)
            grid.addWidget(e, (i - 1) // 3, ((i - 1) % 3) * 2 + 1)
            self.slot_edits[i] = e
        lo.add(grid)
        lf = ConfigForm(ctx.settings.loadout)
        lf.changed.connect(ctx.settings_edited)
        self.loadout_form = lf
        lo.add(lf)
        pb = QHBoxLayout()
        for text, key in (("Pick search box on screen", "search"), ("Pick first result on screen", "result")):
            b = QPushButton(icon("crosshair"), f"  {text}")
            b.clicked.connect(lambda _=False, k=key: self._pick_loadout(k))
            pb.addWidget(b)
        pb.addStretch(1)
        lo.add(pb)
        root.addWidget(lo)
        root.addStretch(1)
        self.reload()

    # ------------------------------------------------------------------ list
    def reload(self) -> None:
        self._loading = True
        self.list.clear()
        for r in self.ctx.settings.routines:
            it = QListWidgetItem(r.name + ("  (verify)" if r.verify else ""))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if r.enabled else Qt.Unchecked)
            self.list.addItem(it)
        self._loading = False
        self.watcher.clear()
        self.watcher.addItems([""] + [w.name for w in self.ctx.settings.watchers])
        if self.ctx.settings.routines:
            self.list.setCurrentRow(0)
        else:
            self._select(-1)

    def _toggled(self, item) -> None:
        if self._loading:
            return
        r = self.ctx.settings.routines[self.list.row(item)]
        r.enabled = item.checkState() == Qt.Checked
        if self.current is r:
            self.enabled.setChecked(r.enabled)
        self.ctx.save_settings()

    def _add(self, r: Routine) -> None:
        names = {x.name for x in self.ctx.settings.routines}
        base, i = r.name, 2
        while r.name in names:
            r.name, i = f"{base} ({i})", i + 1
        self.ctx.settings.routines.append(r)
        self.ctx.save_settings()
        self.reload()
        self.list.setCurrentRow(len(self.ctx.settings.routines) - 1)

    def _new(self) -> None:
        self._add(Routine("New routine", steps=[RoutineStep("use_item", "Item name")]))

    def _dup(self) -> None:
        if self.current:
            self._add(copy.deepcopy(self.current))

    def _delete(self) -> None:
        if self.current and QMessageBox.question(self, "Routines", f"Delete '{self.current.name}'?") == QMessageBox.Yes:
            self.ctx.settings.routines.remove(self.current)
            self.current = None
            self.ctx.save_settings()
            self.reload()

    def _run_now(self) -> None:
        if self.current:
            self._save_fields()
            self.run_lbl.setText(self.ctx.engine.run_routine_now(self.current.name))

    # ------------------------------------------------------------------ editor
    def _select(self, row: int) -> None:
        rs = self.ctx.settings.routines
        self.current = rs[row] if 0 <= row < len(rs) else None
        self.editor.setEnabled(self.current is not None)
        self.run_btn.setEnabled(self.current is not None)
        if not self.current:
            return
        r = self.current
        self._loading = True
        self.name.setText(r.name)
        self.enabled.setChecked(r.enabled)
        self.trigger.setCurrentText(r.trigger)
        self.interval.setValue(r.interval_min)
        self.catches.setValue(r.every_catches)
        self.watcher.setCurrentText(r.watcher)
        self.cooldown.setValue(r.cooldown_min)
        self.repeat_until.setText(r.repeat_until)
        self.max_repeats.setValue(r.max_repeats)
        self.reequip.setChecked(r.reequip_rod)
        self.note.setPlainText(r.note)
        self.verify_badge.setVisible(r.verify)
        self._fill_steps()
        self._loading = False
        self._update_trigger_fields()

    def _update_trigger_fields(self) -> None:
        t = self.trigger.currentText()
        self.interval.setEnabled(t == "interval")
        self.catches.setEnabled(t == "catches")
        self.watcher.setEnabled(t == "watcher")

    def _save_fields(self, *_) -> None:
        if self._loading or not self.current:
            return
        r = self.current
        old_name = r.name
        r.name = self.name.text().strip() or r.name
        r.enabled = self.enabled.isChecked()
        r.trigger = self.trigger.currentText()
        r.interval_min = self.interval.value()
        r.every_catches = self.catches.value()
        r.watcher = self.watcher.currentText().strip()
        r.cooldown_min = self.cooldown.value()
        r.repeat_until = self.repeat_until.text().strip()
        r.max_repeats = self.max_repeats.value()
        r.reequip_rod = self.reequip.isChecked()
        r.note = self.note.toPlainText()
        self._update_trigger_fields()
        if r.name != old_name or self.list.currentItem() and self.list.currentItem().checkState() != \
                (Qt.Checked if r.enabled else Qt.Unchecked):
            row = self.list.currentRow()
            self._loading = True
            it = self.list.item(row)
            it.setText(r.name + ("  (verify)" if r.verify else ""))
            it.setCheckState(Qt.Checked if r.enabled else Qt.Unchecked)
            self._loading = False
        self.ctx.save_settings()

    # ------------------------------------------------------------------ steps
    def _fill_steps(self) -> None:
        self.steps.setRowCount(0)
        for st in self.current.steps:
            self._append_row(st)

    def _append_row(self, st: RoutineStep) -> None:
        row = self.steps.rowCount()
        self.steps.insertRow(row)
        kind = QComboBox()
        for i, (k, text) in enumerate(STEP_KINDS.items()):
            kind.addItem(text, k)
            kind.setItemData(i, STEP_HELP[k], Qt.ToolTipRole)
        kind.setCurrentIndex(list(STEP_KINDS).index(st.kind) if st.kind in STEP_KINDS else 0)
        kind.currentIndexChanged.connect(lambda _=0, w=kind: self._edit_step(w))
        self.steps.setCellWidget(row, 0, kind)
        value = QLineEdit(st.value)
        value.editingFinished.connect(lambda w=value: self._edit_step(w))
        self.steps.setCellWidget(row, 1, value)
        sec = _spin(0, 600, st.seconds, 0.1, 1)
        sec.valueChanged.connect(lambda _=0, w=sec: self._edit_step(w))
        self.steps.setCellWidget(row, 2, sec)
        for col, v in ((3, st.x), (4, st.y)):
            sp = _spin(0, 1, v, 0.01, 3)
            sp.valueChanged.connect(lambda _=0, w=sp: self._edit_step(w))
            self.steps.setCellWidget(row, col, sp)
        pick = QPushButton(icon("crosshair"), "")
        pick.setToolTip("Pick the click point on a screenshot")
        pick.clicked.connect(lambda _=False, w=pick: self._pick_step_point(w))
        self.steps.setCellWidget(row, 5, pick)

    def _row_of(self, widget) -> int:
        for r in range(self.steps.rowCount()):
            for c in range(self.steps.columnCount()):
                if self.steps.cellWidget(r, c) is widget:
                    return r
        return -1

    def _edit_step(self, widget) -> None:
        r = self._row_of(widget)
        if r < 0 or not self.current:
            return
        st = self.current.steps[r]
        st.kind = self.steps.cellWidget(r, 0).currentData()
        st.value = self.steps.cellWidget(r, 1).text()
        st.seconds = self.steps.cellWidget(r, 2).value()
        st.x = self.steps.cellWidget(r, 3).value()
        st.y = self.steps.cellWidget(r, 4).value()
        self.ctx.save_settings()

    def _add_step(self) -> None:
        if self.current:
            st = RoutineStep("wait", "", 1.0)
            self.current.steps.append(st)
            self._append_row(st)
            self.ctx.save_settings()

    def _remove_step(self) -> None:
        r = self.steps.currentRow()
        if self.current and 0 <= r < len(self.current.steps):
            del self.current.steps[r]
            self._fill_steps()
            self.ctx.save_settings()

    def _move_step(self, d: int) -> None:
        r = self.steps.currentRow()
        steps = self.current.steps if self.current else []
        if 0 <= r < len(steps) and 0 <= r + d < len(steps):
            steps[r], steps[r + d] = steps[r + d], steps[r]
            self._fill_steps()
            self.steps.setCurrentCell(r + d, 1)
            self.ctx.save_settings()

    def _pick_step_point(self, widget) -> None:
        r = self._row_of(widget)
        if r < 0 or not self.pick_point:
            return
        st = self.current.steps[r]
        val = self.pick_point("Pick click point", "Click where this step should click.", (st.x, st.y))
        if val:
            self.steps.cellWidget(r, 3).setValue(val[0])
            self.steps.cellWidget(r, 4).setValue(val[1])
            if st.kind not in ("click",):
                self.steps.cellWidget(r, 0).setCurrentIndex(list(STEP_KINDS).index("click"))

    # ------------------------------------------------------------------ loadout
    def _set_slot(self, i: int, text: str) -> None:
        self.ctx.settings.loadout.slots[str(i)] = text.strip()
        self.ctx.save_settings()

    def _pick_loadout(self, key: str) -> None:
        if not self.pick_point:
            return
        lo = self.ctx.settings.loadout
        hint = ("Open your inventory in Roblox first, then click the search box." if key == "search"
                else "Search for an item first, then click where the first result appears.")
        val = self.pick_point("Pick inventory position", hint, (getattr(lo, f"{key}_x"), getattr(lo, f"{key}_y")))
        if val:
            setattr(lo, f"{key}_x", round(val[0], 3))
            setattr(lo, f"{key}_y", round(val[1], 3))
            self.loadout_form.set_target(lo)
            self.ctx.save_settings()

    def refresh(self) -> None:
        name = self.ctx.engine.routine_running
        if name:
            self.run_lbl.setText(f"Running '{name}'...")
