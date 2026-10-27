"""Fishing Add-ons: Sovereign recharge, Auto Totem, Auto Appraise, potion, Astral Activator, items."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from fischmacro.game_data import RELICS, SURGES, TRAITS, WEATHERS
from fischmacro.ui.components import AddonCard, ChipCatalogue, DotCombo, NumberBox
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import KeyEdit, page_header

NONE = ("None", None)


def _scroll(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(inner)
    return sa


def _pick_button(text: str = "Pick on screen") -> QPushButton:
    b = QPushButton(icon("crosshair", C["muted"], 16), " " + text)
    b.setCursor(Qt.PointingHandCursor)
    return b


class AddonsPage(QWidget):
    def __init__(self, ctx, pick_region=None, pick_point=None):
        super().__init__()
        self.ctx = ctx
        self.pick_region = pick_region
        self.pick_point = pick_point
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 0)
        outer.setSpacing(12)
        outer.addWidget(page_header("Fishing Add-ons", "Extras that run between catches, never during a minigame. "
                                                       "Tick one to turn it on, click it to see its settings."))
        inner = QWidget()
        self.col = QVBoxLayout(inner)
        self.col.setContentsMargins(0, 4, 10, 24)
        self.col.setSpacing(12)
        wrap = QHBoxLayout()
        wrap.addWidget(inner, 10)
        wrap.addStretch(1)
        holder = QWidget()
        holder.setLayout(wrap)
        inner.setMaximumWidth(860)
        outer.addWidget(_scroll(holder), 1)
        self.build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)

    def _save(self) -> None:
        self.ctx.settings_edited("addons")

    def build(self) -> None:
        a = self.ctx.settings.addons
        self.cards: dict[str, AddonCard] = {}

        # ---- Sovereign
        s = a.sovereign
        c = AddonCard("sovereign", "Auto Sovereign Recharge",
                      "Recharges the Sovereign rod as it runs down. Needs the gamepass enchant.", "#F5C542", s.enabled)
        c.toggled.connect(lambda v: (setattr(s, "enabled", v), self._save()))
        g = c.section("Status")
        self.power_val = g.add_value("Sovereign Power", "Read from the screen every few seconds")
        g = c.section("Configuration")
        below = NumberBox(s.recharge_below, 1, 100, " %")
        below.valueChanged.connect(lambda v: (setattr(s, "recharge_below", v), self._save()))
        g.add_row("Recharge below", "Start recharging when power drops under this", below)
        upto = NumberBox(s.charge_up_to, 1, 100, " %")
        upto.valueChanged.connect(lambda v: (setattr(s, "charge_up_to", v), self._save()))
        g.add_row("Charge up to", "Keep using relics until power reaches this", upto)
        relic = DotCombo([(r, None) for r in RELICS], s.relic)
        relic.currentTextChanged.connect(lambda v: (setattr(s, "relic", v), self._save()))
        g.add_row("Relic", "The item used to recharge", relic)
        g = c.section("Screen")
        b = _pick_button()
        b.clicked.connect(lambda: self._pick("power", s, "power_region", "Sovereign power",
                                             "Drag a box around the rod power number"))
        g.add_row("Power readout", "Where the power % is shown on screen", b)
        c.note("Verify in game: the recharge flow with the gamepass enchant is not documented anywhere, "
               "so check one recharge while you watch.")
        self._add("sovereign", c)

        # ---- Totem
        t = a.totem
        c = AddonCard("totem", "Auto Totem",
                      "Holds the weather, time of day and surge you want by using totems.", "#38BDF8", t.enabled)
        c.toggled.connect(lambda v: (setattr(t, "enabled", v), self._save()))
        g = c.section("World")
        self.weather_val = g.add_value("Weather")
        self.time_val = g.add_value("Time of day")
        self.surge_val = g.add_value("Surge")
        g = c.section("Totems")
        weather = DotCombo([NONE] + [(w, col) for w, _, col, _ in WEATHERS], t.weather)
        weather.currentTextChanged.connect(lambda v: (setattr(t, "weather", v), self._save()))
        g.add_row("Totem", "The weather to hold", weather)
        surge = DotCombo([NONE] + [(n, col) for n, _, col, _ in SURGES], t.surge)
        surge.currentTextChanged.connect(lambda v: (setattr(t, "surge", v), self._save()))
        g.add_row("Surge totem", "Keeps a surge running", surge)
        tod = DotCombo([("Auto", None), ("Day", "#FCD34D"), ("Night", "#818CF8")], t.time)
        tod.currentTextChanged.connect(lambda v: (setattr(t, "time", v), self._save()))
        g.add_row("Time of day", "Auto leaves it alone; Day / Night uses the Sundial Totem", tod)
        cd = NumberBox(int(t.cooldown_min), 1, 120, " min")
        cd.valueChanged.connect(lambda v: (setattr(t, "cooldown_min", float(v)), self._save()))
        g.add_row("Wait between uses", "So a totem is not used again while it takes effect", cd)
        g = c.section("Screen")
        b = _pick_button()
        b.clicked.connect(lambda: self._pick("world", t, "world_region", "World readout",
                                             "Drag a box around the weather / time / surge text"))
        g.add_row("World readout", "Where weather and time are shown", b)
        self._add("totem", c)

        # ---- Appraise
        ap = a.appraise
        c = AddonCard("appraise", "Auto Appraise",
                      "Re-rolls a fish at the appraiser until it has the traits you require.", "#A78BFA", None)
        g = c.section("Configuration")
        where = DotCombo([("Appraiser NPC", None), ("Gamepass", None)], ap.mode)
        where.currentTextChanged.connect(lambda v: (setattr(ap, "mode", v), self._save()))
        g.add_row("Appraise at", "Stand at the appraiser, or use the gamepass from anywhere", where)
        tries = NumberBox(ap.max_tries, 1, 500)
        tries.valueChanged.connect(lambda v: (setattr(ap, "max_tries", v), self._save()))
        g.add_row("Stop after", "Most re-rolls to try", tries)
        c.lay.addSpacing(6)
        from fischmacro.ui.components import section_title
        c.lay.addWidget(section_title("Traits - stop when the fish has any of these"))
        traits = ChipCatalogue([(n, "#A78BFA") for n in TRAITS],
                               ap.traits, [x for x in ap.traits if x not in TRAITS],
                               "Search traits, or type one to add")

        def on_traits():
            ap.traits = traits.selected() + traits.custom_selected()
            self._save()
        traits.changed.connect(on_traits)
        c.lay.addWidget(traits)
        row = QHBoxLayout()
        self.appraise_btn = QPushButton(icon("play", C["on_primary"], 16), " Start appraising")
        self.appraise_btn.setObjectName("primary")
        self.appraise_btn.setCursor(Qt.PointingHandCursor)
        self.appraise_btn.clicked.connect(self._appraise)
        self.appraise_msg = c.note("Hold the fish, then press Start - you get 3 seconds to click into Roblox.")
        row.addWidget(self.appraise_btn)
        row.addStretch(1)
        c.lay.addLayout(row)
        self._add("appraise", c)

        # ---- Potion & Astral
        for key, title, desc, col, item, fixed in (
                ("potion", "Auto Potion", "Drinks a potion on a timer while you fish.", "#F472B6", a.potion, False),
                ("astral", "Astral Activator", "Uses the Astral Activator on a timer to switch the telescope on.",
                 "#818CF8", a.astral, True)):
            c = AddonCard(key, title, desc, col, item.enabled)
            c.toggled.connect(lambda v, it=item: (setattr(it, "enabled", v), self._save()))
            g = c.section("Configuration")
            if not fixed:
                name = QLineEdit(item.item)
                name.setPlaceholderText("e.g. Luck Potion")
                name.setMinimumWidth(200)
                name.editingFinished.connect(lambda it=item, w=name: (setattr(it, "item", w.text().strip()), self._save()))
                g.add_row("Potion", "Exact name, as in your inventory", name)
            every = NumberBox(int(item.every_min), 1, 600, " min")
            every.valueChanged.connect(lambda v, it=item: (setattr(it, "every_min", float(v)), self._save()))
            g.add_row("Use every", "First use is after this time, then repeats", every)
            self._add(key, c)

        # ---- Items & inventory
        lo = self.ctx.settings.loadout
        c = AddonCard("rod", "Items & inventory",
                      "Which hotbar slot holds what. Anything else is found by typing its name in the inventory.",
                      "#94A3B8", None)
        g = c.section("Hotbar")
        for slot in [str(i) for i in range(1, 10)]:
            e = QLineEdit(lo.slots.get(slot, ""))
            e.setPlaceholderText("empty")
            e.setMinimumWidth(200)
            e.editingFinished.connect(lambda s_=slot, w=e: (lo.slots.__setitem__(s_, w.text().strip()), self._save()))
            g.add_row(f"Slot {slot}", "", e)
        g = c.section("Inventory")
        k = KeyEdit(lo.inventory_key)
        k.editingFinished.connect(lambda w=k: (setattr(lo, "inventory_key", w.text().strip() or "`"), self._save()))
        g.add_row("Open inventory key", "Verify in Fisch", k)
        b1 = _pick_button()
        b1.clicked.connect(lambda: self._pick_point(lo, "search", "Inventory search box",
                                                    "Open your inventory in Roblox first, then click its search box"))
        g.add_row("Search box", "Where to click before typing an item name", b1)
        b2 = _pick_button()
        b2.clicked.connect(lambda: self._pick_point(lo, "result", "First search result",
                                                    "Click where the first matching item appears"))
        g.add_row("First result", "Clicked to equip the item", b2)
        self._add("items", c)
        self.col.addStretch(1)

    def _add(self, key: str, card: AddonCard) -> None:
        self.cards[key] = card
        self.col.addWidget(card)

    # -- actions
    def _pick(self, _key, obj, attr, title, hint) -> None:
        if not self.pick_region:
            return
        r = self.pick_region(title, hint, getattr(obj, attr))
        if r is not None:
            setattr(obj, attr, r)
            self._save()

    def _pick_point(self, lo, prefix, title, hint) -> None:
        if not self.pick_point:
            return
        p = self.pick_point(title, hint, (getattr(lo, f"{prefix}_x"), getattr(lo, f"{prefix}_y")))
        if p is not None:
            setattr(lo, f"{prefix}_x", round(p[0], 4))
            setattr(lo, f"{prefix}_y", round(p[1], 4))
            self._save()

    def _appraise(self) -> None:
        self.appraise_msg.setText(self.ctx.engine.run_appraise())

    def refresh(self) -> None:
        if not self.isVisible():
            return
        w = self.ctx.engine.addons.world
        self.power_val.setText(f"{w.power}%" if w.power is not None else "---")
        self.weather_val.setText(w.weather or "---")
        self.time_val.setText(w.time or "---")
        self.surge_val.setText(w.surge or ("None" if w.updated else "---"))
