"""Fishing: the few choices that matter, as plain dropdowns. Everything else lives behind 'Advanced'."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from fischmacro.game_data import LULLABY_MODES
from fischmacro.profiles.rod_presets import PRESETS, apply_preset
from fischmacro.ui.components import AddonCard, DotCombo, NumberBox, SquareCheck
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import KeyEdit, page_header

CAST = [("Perfect", "perfect", "Waits for a full power bar"), ("Normal", "normal", "Short, casual cast right away"),
        ("Timed", "timed", "Holds for a fixed time")]
SHAKE = [("Click", "click", "Clicks the shake buttons"), ("Navigation", "navigation", "Uses Roblox UI navigation keys")]
TRACK = [("Standard", "standard", "Follows the fish with the catch bar"),
         ("Precision", "precision", "For tryhard / low-resilience rods with a tiny bar")]
MINI = [("None", "none"), ("Lullaby", "lullaby"), ("Stellarwave", "stellarwave"), ("Targets", "targets")]
MINI_HINT = {"none": "Just the normal catch bar", "lullaby": "Clicks when the pendulum is over a lit section",
             "stellarwave": "Clicks the sign that matches the star", "targets": "Clicks targets as they appear"}


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
        head.addWidget(page_header("Fishing", "How the macro casts, shakes and reels. Saved to the active profile."), 1)
        adv = QPushButton(icon("settings", C["muted"], 16), " Advanced")
        adv.setToolTip("Every number and colour, for fine tuning")
        adv.setCursor(Qt.PointingHandCursor)
        adv.clicked.connect(self.open_advanced)
        head.addWidget(adv, 0, Qt.AlignTop)
        outer.addLayout(head)
        self.inner = QWidget()
        self.inner.setMaximumWidth(860)
        self.col = QVBoxLayout(self.inner)
        self.col.setContentsMargins(0, 4, 10, 24)
        self.col.setSpacing(12)
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

        # ---- basics
        c = AddonCard("fishing", "Fishing loop", "Cast, shake and reel - the main loop.", C["primary"], None,
                      expanded=True)
        c.chevron.hide()
        c.header.mousePressEvent = lambda e: None
        g = c.section("Cast")
        cast = DotCombo([(o[0], None) for o in CAST], _label_for(CAST, p.casting.mode))
        g.add_row("Cast mode", next(o[2] for o in CAST if o[1] == p.casting.mode), cast)
        cast.currentTextChanged.connect(lambda v: (setattr(p.casting, "mode", _value_for(CAST, v)), self._edited(),
                                                   self.build()))
        g = c.section("Shake")
        shake = DotCombo([(o[0], None) for o in SHAKE], _label_for(SHAKE, p.shake.mode))
        g.add_row("Shake mode", next(o[2] for o in SHAKE if o[1] == p.shake.mode), shake)
        shake.currentTextChanged.connect(lambda v: (setattr(p.shake, "mode", _value_for(SHAKE, v)), self._edited(),
                                                    self.build()))
        if p.shake.mode == "navigation":
            k = KeyEdit(p.shake.nav_toggle_key)
            k.editingFinished.connect(lambda w=k: (setattr(p.shake, "nav_toggle_key", w.text().strip()), self._edited()))
            g.add_row("Navigation key", "Must match 'UI Navigation Toggle' in Roblox settings", k)
        g = c.section("Reel")
        track = DotCombo([(o[0], None) for o in TRACK], _label_for(TRACK, p.reel.mode))
        g.add_row("Tracking", next(o[2] for o in TRACK if o[1] == p.reel.mode), track)
        track.currentTextChanged.connect(lambda v: (setattr(p.reel, "mode", _value_for(TRACK, v)), self._edited(),
                                                    self.build()))
        self.col.addWidget(c)

        # ---- rod
        c = AddonCard("rod", "Rod", "Pick your rod, or let the macro read it from the screen.", "#F59E0B", None,
                      expanded=True)
        c.chevron.hide()
        c.header.mousePressEvent = lambda e: None
        g = c.section("Rod")
        self.rod_combo = DotCombo([("Choose a rod...", None)] + [(pr.name, None) for pr in PRESETS])
        self.rod_combo.activated.connect(self._apply_rod)
        g.add_row("Rod settings", "Loads the right minigame and tracking for that rod", self.rod_combo)
        rk = KeyEdit(p.equipment.rod_slot_key)
        rk.setMaximumWidth(90)
        rk.editingFinished.connect(lambda w=rk: (setattr(p.equipment, "rod_slot_key", w.text().strip() or "1"),
                                                 self._edited()))
        g.add_row("Rod hotbar key", "The key that equips your rod", rk)
        auto = SquareCheck(st.rod_detect.enabled)
        auto.toggled.connect(lambda v: (setattr(st.rod_detect, "enabled", v), self.ctx.settings_edited("rod")))
        g.add_row("Detect rod automatically", "Reads the rod name and switches profile on its own", auto)
        pick = QPushButton(icon("crosshair", C["muted"], 16), " Pick on screen")
        pick.setCursor(Qt.PointingHandCursor)
        pick.clicked.connect(self._pick_rod_region)
        g.add_row("Rod name area", "Where the equipped rod's name is shown", pick)
        self.col.addWidget(c)

        # ---- rod minigame
        m = p.minigame
        c = AddonCard("minigame", "Rod minigame", "For rods with their own minigame, like Lullaby or Stellarwave.",
                      "#E879F9", None, expanded=m.kind != "none")
        g = c.section("Minigame")
        kind = DotCombo([(n, None) for n, _ in MINI], _label_for([(n, v, "") for n, v in MINI], m.kind))
        g.add_row("Minigame", MINI_HINT.get(m.kind, ""), kind)
        kind.currentTextChanged.connect(lambda v: (setattr(m, "kind", dict(MINI)[v]), self._edited(), self.build()))
        if m.kind == "lullaby":
            modes = DotCombo([("Keep current", None)] + [(n, col) for n, col, _, _ in LULLABY_MODES], m.lullaby_mode)
            buff = next((b for n, _, _, b in LULLABY_MODES if n == m.lullaby_mode), "Leaves the mode as it is")
            g.add_row("Lullaby mode", buff, modes)
            modes.currentTextChanged.connect(lambda v: (setattr(m, "lullaby_mode", v), self._edited(), self.build()))
            speed = next((s for n, _, s, _ in LULLABY_MODES if n == m.lullaby_mode), None)
            if speed is not None:
                c.note(f"{m.lullaby_mode}: the pendulum runs at {'half' if speed < 1 else 'full'} speed. "
                       "The macro only clicks when the pendulum is over a lit section, once per section, "
                       "and waits out the first 1.2 s of each catch where clicks count for nothing.")
        if m.kind != "none":
            follow = SquareCheck(m.keep_reeling)
            follow.toggled.connect(lambda v: (setattr(m, "keep_reeling", v), self._edited()))
            g.add_row("Also follow the fish", "Keep the catch bar on the fish while doing the minigame", follow)
            lead = NumberBox(int(m.lead_ms), 0, 200, " ms")
            lead.valueChanged.connect(lambda v: (setattr(m, "lead_ms", v), self._edited()))
            g.add_row("Click early by", "Makes up for screen and input delay", lead)
        self.col.addWidget(c)

        # ---- input
        c = AddonCard("hotkeys", "Input", "How keys and clicks reach Roblox.", "#94A3B8", None)
        g = c.section("Input")
        method = DotCombo([("Scan codes (recommended)", None), ("pynput", None)], st.input.method)
        method.currentTextChanged.connect(lambda v: (setattr(st.input, "method", v), self.ctx.settings_edited("input")))
        g.add_row("Input method", "Takes effect next time the app starts", method)
        self.col.addWidget(c)
        self.col.addStretch(1)

    def _apply_rod(self, index: int) -> None:
        if index <= 0:
            return
        pr = PRESETS[index - 1]
        changed = apply_preset(self.ctx.profile, pr)
        self.ctx.save_profile()
        self.ctx.profile_switched.emit()
        QMessageBox.information(self, "Rod", f"Loaded '{pr.name}' settings into '{self.ctx.profile.name}'"
                                + (f": {', '.join(changed)}." if changed else " (already set).") + (
                                    f"\n\n{pr.note}" if pr.note else ""))

    def _pick_rod_region(self) -> None:
        if not self.pick_region:
            return
        rd = self.ctx.settings.rod_detect
        r = self.pick_region("Rod name", "Drag a box around the equipped rod's name", rd.region)
        if r is not None:
            rd.region = r
            self.ctx.settings_edited("rod")

    def open_advanced(self) -> None:
        if not self.advanced_factory:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Advanced fishing settings")
        dlg.resize(980, 720)
        v = QVBoxLayout(dlg)
        page = self.advanced_factory()
        v.addWidget(page, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        dlg.exec()
        self.build()

    def on_profile_switched(self) -> None:
        self.build()
