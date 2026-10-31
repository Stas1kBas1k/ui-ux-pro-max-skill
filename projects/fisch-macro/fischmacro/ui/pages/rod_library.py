"""Rod Library: find your rod on a card, pick its skin, adjust a few settings, save and use it.

Every rod has its own saved profile. Clicking a card loads that profile (or the recommended settings if
the rod has none yet) into a draft; nothing is written until Save. The draft shows a dot while it has
unsaved changes, so a working profile is never overwritten by accident.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from fischmacro.profiles.library import DEFAULT_SKIN, RodLibrary, is_dirty
from fischmacro.rods import behaviour_for
from fischmacro.ui.components import FlowLayout
from fischmacro.ui.icons import icon
from fischmacro.ui.rod_art import rod_pixmap, skin_pixmap
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import ConfigForm, label, page_header

CATEGORIES = ["All", "Special minigame", "Favourites", "Recent", "Configured"]
from fischmacro.rods import STATUS_TEXT  # noqa: E402


def sensitivity(reel) -> int:
    return max(1, min(10, round((reel.kp / 3.0 - 0.5) * 10)))


def set_sensitivity(reel, s: int) -> None:
    k = 0.5 + s / 10
    reel.kp, reel.kd, reel.feedforward = round(3.0 * k, 2), round(0.45 * k, 2), round(0.25 * k, 2)


class RodCard(QFrame):
    clicked = Signal(str)
    favourite_toggled = Signal(str)

    def __init__(self, rod: str, kind: str, special: bool, saved: bool, favourite: bool, tuned: bool = False):
        super().__init__()
        self.rod = rod
        self.setObjectName("rodCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(236, 84)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 8, 10)
        h.setSpacing(12)
        art = QLabel()
        art.setPixmap(rod_pixmap(rod, 56, kind))
        art.setFixedSize(56, 56)
        h.addWidget(art)
        v = QVBoxLayout()
        v.setSpacing(3)
        name = QLabel(rod)
        name.setObjectName("rodName")
        v.addWidget(name)
        sub = QLabel(behaviour_for(kind).label + " minigame" if special else
                     "Tuned settings" if tuned else "Standard reel")
        sub.setObjectName("rodSub")
        v.addWidget(sub)
        tags = QHBoxLayout()
        tags.setSpacing(4)
        if special or tuned:
            tags.addWidget(self._tag("Special" if special else "Preset", "tagSpecial"))
        if saved:
            tags.addWidget(self._tag("Saved", "tagSaved"))
        tags.addStretch(1)
        v.addLayout(tags)
        h.addLayout(v, 1)
        self.star = QPushButton("★" if favourite else "☆")
        self.star.setObjectName("star")
        self.star.setFixedSize(24, 24)
        self.star.setToolTip("Favourite")
        self.star.setCursor(Qt.PointingHandCursor)
        self.star.clicked.connect(lambda: self.favourite_toggled.emit(self.rod))
        h.addWidget(self.star, 0, Qt.AlignTop)

    @staticmethod
    def _tag(text: str, name: str) -> QLabel:
        t = QLabel(text)
        t.setObjectName(name)
        return t

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.rod)


class SkinCard(QPushButton):
    def __init__(self, rod: str, skin: str, kind: str):
        super().__init__()
        self.skin = skin
        self.setObjectName("skinCard")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(92, 92)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 8, 6, 6)
        v.setSpacing(4)
        art = QLabel()
        art.setAlignment(Qt.AlignCenter)
        art.setAttribute(Qt.WA_TransparentForMouseEvents)
        if skin == "+":
            art.setPixmap(icon("plus", C["muted"], 28).pixmap(QSize(28, 28)))
        else:
            art.setPixmap(skin_pixmap(rod, skin, 44, kind))
        v.addWidget(art)
        lab = QLabel("Add skin" if skin == "+" else skin)
        lab.setObjectName("skinName")
        lab.setAlignment(Qt.AlignCenter)
        lab.setWordWrap(True)
        lab.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(lab)


class RodLibraryPage(QWidget):
    start_requested = Signal()
    calibrate_requested = Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.lib = RodLibrary(ctx.profiles, ctx.settings.library)
        self.rod: str | None = None
        self.skin = DEFAULT_SKIN
        self.draft = None
        self.saved = None
        self.cards: dict[str, RodCard] = {}
        self.category = "All"

        root = QHBoxLayout(self)
        root.setContentsMargins(28, 24, 20, 20)
        root.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(page_header("Rod Library", "Click your rod, pick its skin, then press Use. Every rod keeps "
                                                  "its own settings."))
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search rods...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self.fill())
        bar.addWidget(self.search, 1)
        left.addLayout(bar)
        cats = QHBoxLayout()
        cats.setSpacing(6)
        self.cat_btns = {}
        for c in CATEGORIES:
            b = QPushButton(c)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=c: self.set_category(c))
            cats.addWidget(b)
            self.cat_btns[c] = b
        cats.addStretch(1)
        self.count_lbl = label("", "rowHint")
        cats.addWidget(self.count_lbl)
        left.addLayout(cats)
        self.grid_host = QWidget()
        self.grid = FlowLayout(self.grid_host, spacing=10)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(self.grid_host)
        sa.setFrameShape(QFrame.NoFrame)
        left.addWidget(sa, 1)
        root.addLayout(left, 1)

        self.panel = QFrame()
        self.panel.setObjectName("detailPanel")
        self.panel.setFixedWidth(380)
        self.pv = QVBoxLayout(self.panel)
        self.pv.setContentsMargins(18, 18, 18, 18)
        self.pv.setSpacing(10)
        pscroll = QScrollArea()
        pscroll.setWidgetResizable(True)
        pscroll.setWidget(self.panel)
        pscroll.setFrameShape(QFrame.NoFrame)
        pscroll.setFixedWidth(396)
        root.addWidget(pscroll)
        self.set_category("All")
        current = ctx.profile.equipment.rod_name
        if current and current in self.cards:
            self.select(current, ctx.profile.equipment.skin or DEFAULT_SKIN)
        else:
            self._empty_panel()

    # ---------------------------------------------------------------- grid
    def set_category(self, c: str) -> None:
        self.category = c
        for k, b in self.cat_btns.items():
            b.setChecked(k == c)
        self.fill()

    def fill(self) -> None:
        self.lib.refresh()
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.cards.clear()
        rods = self.lib.search(self.search.text(), self.category)
        for rod in rods:
            info = self.lib.info(rod)
            card = RodCard(rod, info.kind, info.special, bool(info.profiles), info.favourite, bool(info.preset_note))
            card.clicked.connect(lambda r: self.select(r))
            card.favourite_toggled.connect(self._toggle_fav)
            card.set_selected(rod == self.rod)
            self.grid.addWidget(card)
            self.cards[rod] = card
        self.count_lbl.setText(f"{len(rods)} rod{'' if len(rods) == 1 else 's'}")
        self.grid_host.adjustSize()

    def _toggle_fav(self, rod: str) -> None:
        on = self.lib.toggle_favourite(rod)
        self.ctx.save_settings()
        card = self.cards.get(rod)
        if card is not None:
            card.star.setText("★" if on else "☆")
        if self.category == "Favourites":
            self.fill()

    # ---------------------------------------------------------------- detail panel
    def _clear_panel(self) -> None:
        def clear(layout):
            while layout.count():
                it = layout.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.setParent(None)  # gone now, not at the next event loop turn
                    w.deleteLater()
                elif it.layout():
                    clear(it.layout())
        clear(self.pv)

    def _empty_panel(self) -> None:
        self._clear_panel()
        self.pv.addWidget(label("Pick a rod", "cardTitle"))
        self.pv.addWidget(label("Click a card on the left. Rods marked Special have their own minigame, which the "
                                "macro plays for you.", "muted", wrap=True))
        self.pv.addStretch(1)

    def select(self, rod: str, skin: str = DEFAULT_SKIN) -> None:
        if self.rod in self.cards:
            self.cards[self.rod].set_selected(False)
        self.rod, self.skin = rod, skin
        if rod in self.cards:
            self.cards[rod].set_selected(True)
        self.draft, created = self.lib.load_or_create(rod, skin, self.ctx.profile)
        self.saved = None if created else copy.deepcopy(self.draft)
        self.build_panel()

    def _select_skin(self, skin: str) -> None:
        if skin == "+":
            name, ok = QInputDialog.getText(self, "Add skin", f"Skin name for {self.rod}:")
            if not ok or not name.strip():
                self.build_panel()
                return
            self.lib.add_skin(self.rod, name.strip())
            self.ctx.save_settings()
            skin = name.strip()
        self.select(self.rod, skin)

    def build_panel(self) -> None:
        self._clear_panel()
        rod, d = self.rod, self.draft
        kind = d.minigame.kind
        b = behaviour_for(kind)
        head = QHBoxLayout()
        art = QLabel()
        art.setPixmap(rod_pixmap(rod, 72, kind, "" if self.skin == DEFAULT_SKIN else self.skin))
        head.addWidget(art)
        tv = QVBoxLayout()
        title = label(rod, "cardTitle")
        title.setWordWrap(True)
        tv.addWidget(title)
        tv.addWidget(label(f"{b.label} · {STATUS_TEXT.get(b.status, b.status)}", "rowHint", wrap=True))
        head.addLayout(tv, 1)
        self.pv.addLayout(head)
        note = self.lib.info(rod).preset_note
        self.pv.addWidget(label(note or b.summary, "muted", wrap=True))
        for n in ([] if note else b.notes):
            self.pv.addWidget(label("• " + n, "rowHint", wrap=True))

        self.pv.addWidget(label("Skin", "sectionTitle"))
        skins = FlowLayout(spacing=8)
        holder = QWidget()
        holder.setLayout(skins)
        for sk in self.lib.skins_for(rod) + ["+"]:
            c = SkinCard(rod, sk, kind)
            c.setChecked(sk == self.skin)
            c.clicked.connect(lambda _=False, sk=sk: self._select_skin(sk))
            skins.addWidget(c)
        self.pv.addWidget(holder)

        self.pv.addWidget(label("Settings", "sectionTitle"))
        row = QHBoxLayout()
        row.addWidget(label("Tracking", "rowTitle"))
        row.addStretch(1)
        self.mode_btns = {}
        for m, text in (("standard", "Standard"), ("precision", "Precision")):
            btn = QPushButton(text)
            btn.setObjectName("chip")
            btn.setCheckable(True)
            btn.setChecked(d.reel.mode == m)
            btn.setToolTip("Precision plans ahead - best for small bars and low-control rods"
                           if m == "precision" else "Works for most rods")
            btn.clicked.connect(lambda _=False, m=m: self._set_mode(m))
            row.addWidget(btn)
            self.mode_btns[m] = btn
        self.pv.addLayout(row)
        srow = QHBoxLayout()
        srow.addWidget(label("Sensitivity", "rowTitle"))
        self.sens = QSlider(Qt.Horizontal)
        self.sens.setRange(1, 10)
        self.sens.setValue(sensitivity(d.reel))
        self.sens.setToolTip("Higher reacts faster to the fish; lower is calmer")
        self.sens_val = label(str(self.sens.value()), "rowHint")
        self.sens.valueChanged.connect(self._set_sens)
        srow.addWidget(self.sens, 1)
        srow.addWidget(self.sens_val)
        self.pv.addLayout(srow)
        if b.settings:
            form = ConfigForm(d.minigame, only=list(b.settings))
            form.changed.connect(lambda *_: self._changed())
            self.pv.addWidget(form)

        self.adv_btn = QPushButton(icon("chevron-down", C["muted"], 14), "  Advanced settings")
        self.adv_btn.setObjectName("flat")
        self.adv_btn.setCheckable(True)
        self.pv.addWidget(self.adv_btn, 0, Qt.AlignLeft)
        self.adv = QWidget()
        av = QVBoxLayout(self.adv)
        av.setContentsMargins(0, 0, 0, 0)
        rf = ConfigForm(d.reel, only=["mpc_margin", "lookahead", "smoothing", "min_confidence", "lost_fish_timeout",
                                      "edge_margin", "auto_hover"])
        rf.changed.connect(lambda *_: self._changed())
        av.addWidget(rf)
        if b.advanced:
            mf = ConfigForm(d.minigame, only=list(b.advanced))
            mf.changed.connect(lambda *_: self._changed())
            av.addWidget(mf)
        self.adv.setVisible(False)
        self.adv_btn.toggled.connect(self.adv.setVisible)
        self.pv.addWidget(self.adv)

        self.state_lbl = label("", "rowHint", wrap=True)
        self.pv.addWidget(self.state_lbl)
        acts = QHBoxLayout()
        self.use_btn = QPushButton(icon("check", C["on_primary"], 16), "")
        self.use_btn.setObjectName("primary")
        self.use_btn.clicked.connect(self.use)
        acts.addWidget(self.use_btn, 1)
        reset = QPushButton(icon("reset", C["muted"], 16), "")
        reset.setToolTip("Reset to recommended settings")
        reset.clicked.connect(self.reset)
        acts.addWidget(reset)
        cal = QPushButton(icon("crosshair", C["muted"], 16), "")
        cal.setToolTip("Calibrate for this rod and skin")
        cal.clicked.connect(self.calibrate_requested)
        acts.addWidget(cal)
        self.pv.addLayout(acts)
        start = QPushButton(icon("play", C["muted"], 16), "  Use and start fishing")
        start.clicked.connect(lambda: self.use() and self.start_requested.emit())
        self.pv.addWidget(start)
        self.pv.addStretch(1)
        self._refresh_state()

    def _set_mode(self, m: str) -> None:
        self.draft.reel.mode = m
        for k, btn in self.mode_btns.items():
            btn.setChecked(k == m)
        self._changed()

    def _set_sens(self, v: int) -> None:
        set_sensitivity(self.draft.reel, v)
        self.sens_val.setText(str(v))
        self._changed()

    def _changed(self) -> None:
        self._refresh_state()

    @property
    def dirty(self) -> bool:
        return self.draft is not None and is_dirty(self.draft, self.saved)

    @property
    def in_use(self) -> bool:
        return self.draft is not None and self.ctx.profile.name == self.draft.name

    def _refresh_state(self) -> None:
        if self.saved is None:
            text, btn = "New profile - not saved yet", "Save and use"
        elif self.dirty:
            text, btn = "● Unsaved changes", "Save and use"
        elif self.in_use:
            text, btn = f"In use · profile '{self.draft.name}'", "In use"
        else:
            text, btn = f"Saved · profile '{self.draft.name}'", "Use this rod"
        self.state_lbl.setText(text)
        self.state_lbl.setStyleSheet(f"color: {C['warning'] if self.dirty or self.saved is None else C['muted']};")
        self.use_btn.setText("  " + btn)
        self.use_btn.setEnabled(not (self.in_use and not self.dirty and self.saved is not None))

    def use(self) -> bool:
        """Save the draft (if needed) and make it the active profile."""
        if self.draft is None:
            return False
        if self.saved is None or self.dirty:
            self.lib.save(self.draft)
            self.saved = copy.deepcopy(self.draft)
        self.lib.mark_used(self.rod)
        self.ctx.settings.rod_detect.enabled = False
        self.ctx._use_profile(copy.deepcopy(self.draft))
        self.ctx.notice.emit("Rod", f"Using {self.rod}" + ("" if self.skin == DEFAULT_SKIN else f" ({self.skin})"))
        card = self.cards.get(self.rod)
        self._refresh_state()
        if card is not None and self.category in ("Configured", "Recent"):
            self.fill()
        return True

    def reset(self) -> None:
        self.draft = self.lib.recommended(self.rod, self.skin, self.ctx.profile)
        if self.saved is not None:
            self.draft.name = self.saved.name
        self.build_panel()
