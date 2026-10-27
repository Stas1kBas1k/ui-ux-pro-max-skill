from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from fischmacro.profiles.manager import ProfileError
from fischmacro.profiles.schema import DEFAULT_REGIONS
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import Card, label, page_header


class ProfilesPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(page_header("Profiles", "A profile stores the complete configuration: regions, detection "
                                               "colours, casting, shake, reel tuning, timeouts and modules. "
                                               "Make one per rod or setup."))
        row = QHBoxLayout()
        row.setSpacing(14)
        left = Card("Saved profiles")
        self.list = QListWidget()
        self.list.setMinimumWidth(260)
        self.list.itemDoubleClicked.connect(lambda _: self._activate())
        left.add(self.list)
        grid = QHBoxLayout()
        self.btns = {}
        for key, ic, text in [("new", "plus", "New"), ("dup", "copy", "Duplicate"), ("ren", "edit", "Rename"),
                              ("del", "trash", "Delete")]:
            b = QPushButton(icon(ic), f" {text}")
            grid.addWidget(b)
            self.btns[key] = b
        left.add(grid)
        grid2 = QHBoxLayout()
        for key, ic, text in [("imp", "upload", "Import"), ("exp", "download", "Export")]:
            b = QPushButton(icon(ic), f" {text}")
            grid2.addWidget(b)
            self.btns[key] = b
        left.add(grid2)
        self.activate_btn = QPushButton(icon("check", "#FFFFFF"), "  Use selected profile")
        self.activate_btn.setObjectName("primary")
        left.add(self.activate_btn)
        row.addWidget(left, 2)

        right = Card("Active profile")
        self.active_lbl = label("", "cardTitle")
        self.active_lbl.setStyleSheet(f"font-size: 14pt; color: {C['primary_hi']};")
        right.add(self.active_lbl)
        self.summary = label("", "muted", wrap=True)
        right.add(self.summary)
        right.add(label("Rod name", "faint"))
        self.rod_edit = QLineEdit()
        self.rod_edit.editingFinished.connect(self._save_rod)
        right.add(self.rod_edit)
        right.add(label("Notes", "faint"))
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("e.g. tuned for Rod of the Depths, 1920x1080 borderless, 125% DPI")
        self.notes.textChanged.connect(self._save_notes)
        right.add(self.notes)
        reset = QPushButton(icon("reset"), "  Reset regions to defaults")
        reset.clicked.connect(self._reset_regions)
        right.add(reset)
        row.addWidget(right, 3)
        root.addLayout(row, 1)

        self.btns["new"].clicked.connect(self._new)
        self.btns["dup"].clicked.connect(self._dup)
        self.btns["ren"].clicked.connect(self._rename)
        self.btns["del"].clicked.connect(self._delete)
        self.btns["imp"].clicked.connect(self._import)
        self.btns["exp"].clicked.connect(self._export)
        self.activate_btn.clicked.connect(self._activate)
        self.reload()

    # ------------------------------------------------------------------
    def reload(self) -> None:
        names = self.ctx.profiles.names()
        self.list.clear()
        for n in names:
            item = QListWidgetItem(icon("fish", C["primary_hi"] if n == self.ctx.profile.name else C["faint"]), n)
            self.list.addItem(item)
            if n == self.ctx.profile.name:
                self.list.setCurrentItem(item)
        p = self.ctx.profile
        self.active_lbl.setText(p.name)
        calibrated = sum(1 for k, r in p.regions.items() if k in DEFAULT_REGIONS and r != DEFAULT_REGIONS[k])
        enabled_mods = [k for k, v in p.modules.items() if v.get("enabled")]
        self.summary.setText(
            f"Shake mode: {p.shake.mode}   ·   Cast: {p.casting.mode}   ·   Kp {p.reel.kp:g} / Kd {p.reel.kd:g}\n"
            f"Calibrated regions: {calibrated}/{len(DEFAULT_REGIONS)}   ·   Modules: {', '.join(enabled_mods) or 'none'}")
        self.rod_edit.setText(p.equipment.rod_name)
        self.notes.blockSignals(True)
        self.notes.setPlainText(p.notes)
        self.notes.blockSignals(False)

    def _selected(self) -> str | None:
        it = self.list.currentItem()
        return it.text() if it else None

    def _err(self, exc: Exception) -> None:
        QMessageBox.warning(self, "Profiles", str(exc))

    def _ask(self, title: str, text: str = "") -> str | None:
        name, ok = QInputDialog.getText(self, title, "Profile name:", text=text)
        return name.strip() if ok and name.strip() else None

    def _new(self) -> None:
        name = self._ask("New profile")
        if name:
            try:
                self.ctx.profiles.create(name)
            except ProfileError as e:
                return self._err(e)
            self.reload()

    def _dup(self) -> None:
        src = self._selected()
        if not src:
            return
        self.ctx.save_profile()
        name = self._ask("Duplicate profile", f"{src} copy")
        if name:
            try:
                self.ctx.profiles.duplicate(src, name)
            except ProfileError as e:
                return self._err(e)
            self.reload()

    def _rename(self) -> None:
        old = self._selected()
        if not old:
            return
        new = self._ask("Rename profile", old)
        if not new or new == old:
            return
        try:
            if old == self.ctx.profile.name:
                self.ctx.save_profile()
                renamed = self.ctx.profiles.rename(old, new)
                self.ctx.reload_profile_object(renamed)
            else:
                self.ctx.profiles.rename(old, new)
        except ProfileError as e:
            return self._err(e)
        self.reload()

    def _delete(self) -> None:
        name = self._selected()
        if not name:
            return
        if name == self.ctx.profile.name:
            return self._err(ProfileError("Switch to another profile before deleting this one."))
        if QMessageBox.question(self, "Delete profile", f"Delete profile '{name}'? This cannot be undone.") \
                != QMessageBox.Yes:
            return
        try:
            self.ctx.profiles.delete(name)
        except ProfileError as e:
            return self._err(e)
        self.reload()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import profile", "", "Profile (*.json)")
        if path:
            try:
                p = self.ctx.profiles.import_file(path)
            except ProfileError as e:
                return self._err(e)
            QMessageBox.information(self, "Import", f"Imported as '{p.name}'.")
            self.reload()

    def _export(self) -> None:
        name = self._selected()
        if not name:
            return
        self.ctx.save_profile()
        path, _ = QFileDialog.getSaveFileName(self, "Export profile", f"{name}.json", "Profile (*.json)")
        if path:
            try:
                self.ctx.profiles.export(name, path)
            except (ProfileError, OSError) as e:
                return self._err(e)

    def _activate(self) -> None:
        name = self._selected()
        if not name or name == self.ctx.profile.name:
            return
        try:
            self.ctx.switch_profile(name)
        except ProfileError as e:
            return self._err(e)
        self.reload()

    def _save_rod(self) -> None:
        self.ctx.profile.equipment.rod_name = self.rod_edit.text().strip()
        self.ctx.profile_edited()

    def _save_notes(self) -> None:
        self.ctx.profile.notes = self.notes.toPlainText()
        self.ctx.profile_edited()

    def _reset_regions(self) -> None:
        if QMessageBox.question(self, "Reset regions", "Reset all screen regions of this profile to the defaults?") \
                == QMessageBox.Yes:
            import copy
            self.ctx.profile.regions = copy.deepcopy(DEFAULT_REGIONS)
            self.ctx.save_profile()
            self.ctx.profile_switched.emit()

    def on_profile_switched(self) -> None:
        self.reload()

    def set_locked(self, locked: bool) -> None:
        for k in ("ren", "del", "imp"):
            self.btns[k].setEnabled(not locked)
        self.activate_btn.setEnabled(not locked)
        self.activate_btn.setToolTip("Stop automation to switch profiles." if locked else "")
        self.list.setEnabled(True)
        self.list.setFocusPolicy(Qt.StrongFocus)
