"""AI assistant: ask anything (answers use live web search) and let it read the game screen."""
from __future__ import annotations

import html
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QTextBrowser, QVBoxLayout, QWidget,
)

from fischmacro.ui.components import AddonCard, DotCombo, NumberBox, RowGroup, SquareCheck, section_title
from fischmacro.ui.icons import icon
from fischmacro.ui.theme import C, rgba
from fischmacro.ui.widgets import page_header

SUGGESTIONS = [("Best rod right now?", "What's the best rod I can get right now, and how?"),
               ("Best enchant?", "Which enchant should I put on my rod for money and for luck?"),
               ("Where's Megalodon?", "Where and when can I catch Megalodon?"),
               ("Lullaby modes?", "What does each Lullaby rod mode do, and which is best for AFK?")]


class AssistantPage(QWidget):
    _answer = Signal(object)    # (question, Answer | str error)
    _reading_error = Signal(str)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.busy = False
        a = ctx.settings.ai
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(12)
        root.addWidget(page_header("Assistant", "Ask anything about Fisch (or anything else). Answers search the "
                                                "web, so they follow the latest updates."))

        body = QHBoxLayout()
        body.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(10)
        self.chat = QTextBrowser()
        self.chat.setObjectName("chat")
        self.chat.setOpenExternalLinks(True)
        left.addWidget(self.chat, 1)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for short, q in SUGGESTIONS:
            b = QPushButton(short)
            b.setToolTip(q)
            b.setObjectName("chip")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, q=q: self.send(q))
            chips.addWidget(b)
        chips.addStretch(1)
        left.addLayout(chips)
        bar = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setObjectName("search")
        self.input.setPlaceholderText("Ask a question...")
        self.input.returnPressed.connect(lambda: self.send(self.input.text()))
        self.with_screen = SquareCheck(False)
        self.with_screen.setToolTip("Attach a screenshot of the game to this question")
        self.send_btn = QPushButton(icon("play", C["on_primary"], 16), " Ask")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(lambda: self.send(self.input.text()))
        bar.addWidget(self.input, 1)
        bar.addWidget(self.with_screen)
        bar.addWidget(self._small("+ screen"))
        bar.addWidget(self.send_btn)
        left.addLayout(bar)
        body.addLayout(left, 3)

        side = QWidget()
        side.setMinimumWidth(400)
        right = QVBoxLayout(side)
        right.setContentsMargins(0, 0, 8, 0)
        right.setSpacing(10)
        setup = AddonCard("settings", "Set up", "Uses your own Claude API key. Off until you add one.", C["accent"],
                          None, expanded=not ctx.assistant.configured)
        g = setup.section("Account")
        self.key = QLineEdit(a.api_key)
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("sk-ant-...")
        self.key.setMinimumWidth(180)
        self.key.editingFinished.connect(self._save_key)
        g.add_row("API key", "From console.anthropic.com", self.key)
        effort = DotCombo([("low", None), ("medium", None), ("high", None)], a.effort)
        effort.setMinimumWidth(110)
        effort.currentTextChanged.connect(lambda v: (setattr(a, "effort", v), ctx.settings_edited("ai")))
        g.add_row("Answer depth", "Higher is more thorough and slower", effort)
        g = setup.section("Screen")
        allow = SquareCheck(a.allow_screenshots)
        allow.toggled.connect(lambda v: (setattr(a, "allow_screenshots", v), ctx.settings_edited("ai"),
                                         self._refresh_state()))
        g.add_row("Let it see the game", "Screenshots are sent to Anthropic only when it reads the screen", allow)
        every = NumberBox(a.auto_read_min, 0, 120, " min")
        every.valueChanged.connect(lambda v: (setattr(a, "auto_read_min", v), ctx.settings_edited("ai")))
        g.add_row("Read the game every", "0 = only when you press the button. Each read uses credits", every)
        right.addWidget(setup)

        right.addWidget(section_title("What it sees in your game"))
        rg = RowGroup()
        self.vals = {k: rg.add_value(t) for k, t in (("weather", "Weather"), ("time_of_day", "Time of day"),
                                                     ("surge", "Surge"), ("rod", "Rod"), ("rod_skin", "Skin"),
                                                     ("enchant", "Enchant"), ("events", "Events / hunts"))}
        right.addWidget(rg)
        self.read_btn = QPushButton(icon("vision", C["muted"], 16), " Read my game now")
        self.read_btn.clicked.connect(self._read)
        right.addWidget(self.read_btn)
        self.status = QLineEdit()
        self.status.setReadOnly(True)
        self.status.setObjectName("statusLine")
        right.addWidget(self.status)
        right.addStretch(1)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(side)
        sa.setMinimumWidth(420)
        body.addWidget(sa, 2)
        root.addLayout(body, 1)

        self._answer.connect(self._show_answer)
        self._reading_error.connect(lambda m: self.status.setText(m))
        ctx.ai_reading.connect(self._show_reading)
        self._welcome()
        self._refresh_state()
        if ctx.last_ai_reading:
            self._show_reading(ctx.last_ai_reading)

    def _small(self, text):
        from fischmacro.ui.widgets import label
        return label(text, "rowHint")

    def _save_key(self) -> None:
        self.ctx.settings.ai.api_key = self.key.text().strip()
        self.ctx.settings_edited("ai")
        self._refresh_state()

    def _refresh_state(self) -> None:
        ok = self.ctx.assistant.configured
        allow = self.ctx.settings.ai.allow_screenshots
        self.send_btn.setEnabled(ok and not self.busy)
        self.read_btn.setEnabled(ok and allow)
        self.with_screen.setEnabled(ok and allow)
        if not ok:
            self.status.setText("Add an API key to start")
        elif not allow:
            self.status.setText("Tick 'Let it see the game' to read the screen")

    # -- chat
    def _bubble(self, who: str, text_html: str) -> None:
        mine = who == "you"
        bg = rgba(C["primary"], 0.18) if mine else C["surface"]
        align = "right" if mine else "left"
        self.chat.append(f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td align="{align}">'
                         f'<div style="background:{bg}; border-radius:10px; padding:8px 11px; margin:4px 0;">'
                         f'{text_html}</div></td></tr></table>')

    def _welcome(self) -> None:
        self._bubble("ai", "Hi! Ask me anything - best rods, enchants, where to catch something, what an event "
                           "does. I search the web so answers follow the latest Fisch updates.")

    def send(self, question: str) -> None:
        q = question.strip()
        if not q or self.busy:
            return
        if not self.ctx.assistant.configured:
            self.status.setText("Add an API key first (Set up)")
            return
        shot = None
        if self.with_screen.isChecked():
            shot = self.ctx.engine._grab_full_image()
            if shot is None:
                self.status.setText("Could not capture the game - asking without the screenshot")
        self.input.clear()
        self._bubble("you", html.escape(q) + (" <i>(+ screenshot)</i>" if shot is not None else ""))
        self.busy = True
        self._refresh_state()
        self.status.setText("Thinking and searching...")

        def work():
            from fischmacro.ai.assistant import AssistantError
            try:
                self._answer.emit(self.ctx.assistant.ask(q, shot))
            except AssistantError as exc:
                self._answer.emit(str(exc))
            except Exception as exc:  # noqa: BLE001 - never crash the UI thread over a network call
                self._answer.emit(f"Something went wrong: {exc}")
        threading.Thread(target=work, name="ai-ask", daemon=True).start()

    def _show_answer(self, ans) -> None:
        self.busy = False
        self._refresh_state()
        if isinstance(ans, str):
            self._bubble("ai", f'<span style="color:{C["danger_hi"]}">{html.escape(ans)}</span>')
            self.status.setText(ans)
            return
        body = html.escape(ans.text).replace("\n", "<br>")
        if ans.sources:
            links = " · ".join(f'<a href="{html.escape(u)}" style="color:{C["accent"]}">{html.escape(t[:40])}</a>'
                               for t, u in ans.sources)
            body += f'<br><span style="color:{C["faint"]}">Sources: {links}</span>'
        self._bubble("ai", body)
        self.status.setText("Done")

    # -- screen reading
    def _read(self) -> None:
        self.status.setText("Reading your game...")
        self.ctx.read_game_with_ai(on_error=self._reading_error.emit)

    def _show_reading(self, r: dict) -> None:
        for k, lab in self.vals.items():
            v = r.get(k)
            if isinstance(v, list):
                v = ", ".join((r.get("events") or []) + (r.get("hunts") or []))
            lab.setText(v or "---")
        self.status.setText(r.get("notes") or "Read the game")
