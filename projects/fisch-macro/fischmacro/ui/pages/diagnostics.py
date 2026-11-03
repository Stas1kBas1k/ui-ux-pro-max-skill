"""Diagnostics: what the engine is doing right now, the last inputs, retries, errors and transitions."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from fischmacro.input.controller import ObservedBackend
from fischmacro.ui.components import SquareCheck
from fischmacro.ui.theme import C
from fischmacro.ui.widgets import label, page_header


def _rows(pairs) -> str:
    return "".join(f'<tr><td style="color:{C["muted"]}; padding-right:14px">{html.escape(k)}</td>'
                   f'<td>{html.escape(str(v))}</td></tr>' for k, v in pairs)


def _section(title: str, body: str) -> str:
    return f'<h3 style="margin:10px 0 4px 0">{html.escape(title)}</h3>{body}'


def diagnostics_html(eng) -> str:
    """Plain HTML of the engine state (kept separate from the widget so it can be tested)."""
    s = eng.snapshot()
    f = eng.fsm
    back = eng.inputs.backend
    obs = s.observation
    out = []
    out.append(_section("Engine", "<table>" + _rows([
        ("Status", s.status.value), ("Fishing state", s.fsm_state), ("Game looks like", s.game_state),
        ("Message", s.message or "-"), ("Last error", s.last_error or "-"),
        ("Input", getattr(back, "name", "?") + ("  - OBSERVE ONLY, nothing is sent"
                                                 if isinstance(back, ObservedBackend) and back.dry_run else "")),
        ("Held now", ", ".join(s.held_inputs) or "nothing"),
        ("Frames / s", f"{s.fps:.0f}"), ("Capture ms", f"{s.capture_ms:.1f}"), ("Vision ms", f"{s.process_ms:.1f}"),
        ("Window found / focused", f"{s.window_found} / {s.window_focused}"),
    ]) + "</table>"))
    if obs is not None:
        r = obs.reel
        out.append(_section("Detection (last frame)", "<table>" + _rows([
            ("Reel", f"{'yes' if r.ui_present else 'no'} - fish {'%.3f' % r.fish_x if r.fish_found else '-'} "
                     f"(conf {r.fish_confidence:.2f}), bar {'%.3f-%.3f' % (r.bar_left, r.bar_right) if r.bar_found else '-'}"),
            ("Shake", "yes" if obs.shake.present else "no"),
            ("Progress", f"{obs.progress.fill:.2f}" if obs.progress.present else "-"),
            ("Checked", ", ".join(obs.checked) or "-"),
        ]) + "</table>"))
    tr = f.tracker.state
    out.append(_section("Fish tracking (filtered)", "<table>" + _rows([
        ("Usable", "yes" if tr.usable else "no" + (f" (lost {tr.lost_for:.2f} s)" if tr.lost_for else "")),
        ("Fish", f"{tr.fish_x:.3f}, moving {tr.direction} at {abs(tr.fish_v):.2f}/s" if tr.usable else "-"),
        ("Bar", f"{tr.bar_left:.3f}-{tr.bar_right:.3f}" if tr.usable and tr.bar_right > tr.bar_left else "-"),
        ("Confidence", f"{tr.confidence:.0%}" + ("  (bridging a missed frame)" if tr.coasting else "")),
        ("Wrong detections ignored", tr.rejected),
        ("Controller", f"{f.reel.debug.reason} · duty {f.reel.debug.duty:.2f}" if hasattr(f.reel.debug, "reason") else "-"),
    ]) + "</table>"))
    if eng.start_report:
        out.append(_section("Last Start", "<table>" + _rows(
            [(n, ("ok" if ok else "FAILED") + (f" - {d}" if d else "")) for n, ok, d in eng.start_report]) + "</table>"))
    sess = eng.session
    rc = eng.addons.recharge
    out.append(_section("Retries and recoveries", "<table>" + _rows([
        ("Recoveries this session", sess.recoveries), ("Recoveries in a row", f.consecutive_recoveries),
        ("Casts with power bar seen", f.cast_bar_seen_count),
        ("Rod minigame", f"{f.profile.minigame.kind}: {f.minigame.hits} hit, {f.minigame.misses} missed"),
        ("Sovereign recharge", f"{rc.state.value} ({rc.failures} failed)" + (f" - {rc.last_message}" if rc.last_message else "")),
    ]) + "</table>"))
    if isinstance(back, ObservedBackend) and back.recent:
        now = time.time()
        rows = [(f"{now - t:5.1f} s ago", what + ("" if sent else f"  [not sent: {err}]"))
                for t, what, sent, err in list(back.recent)[-14:][::-1]]
        out.append(_section("Last inputs", "<table>" + _rows(rows) + "</table>"))
    if f.history:
        now = time.perf_counter()
        rows = [(f"{now - t:6.1f} s ago", f"{a.value} -> {b.value}  ({why})") for t, a, b, why in f.history[-12:][::-1]]
        out.append(_section("Recent transitions", "<table>" + _rows(rows) + "</table>"))
    if f.minigame.log:
        out.append(_section("Rod minigame log", "<br>".join(html.escape(x) for x in list(f.minigame.log)[-10:])))
    if f.time_in_state:
        total = sum(f.time_in_state.values()) or 1.0
        out.append(_section("Where the time went", "<table>" + _rows(
            [(k, f"{v:.1f} s ({v / total:.0%})") for k, v in sorted(f.time_in_state.items(), key=lambda x: -x[1])])
            + "</table>"))
    return "".join(out)


class DiagnosticsPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(10)
        root.addWidget(page_header("Diagnostics", "What the macro sees and does, live. Use 'Observe only' to "
                                                  "let it watch and decide without sending any input."))
        bar = QHBoxLayout()
        self.observe = SquareCheck(ctx.settings.input.observe_only)
        self.observe.toggled.connect(self._observe)
        bar.addWidget(self.observe)
        bar.addWidget(label("Observe only (no input is sent; takes effect on the next Start)", "rowHint"))
        bar.addStretch(1)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._copy)
        bar.addWidget(copy_btn)
        root.addLayout(bar)
        from PySide6.QtWidgets import QSplitter
        from PySide6.QtCore import Qt
        from fischmacro.ui.widgets import ImageView
        split = QSplitter(Qt.Vertical)
        # live view: the game with what the macro detected and the inputs it sent drawn on top
        self.live = ImageView("Live view appears while the game is being watched (press Start or Watch the game)")
        split.addWidget(self.live)
        self.view = QTextBrowser()
        self.view.setObjectName("chat")
        split.addWidget(self.view)
        split.setSizes([420, 300])
        root.addWidget(split, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)

    def _observe(self, on: bool) -> None:
        self.ctx.settings.input.observe_only = on
        self.ctx.settings_edited("input")

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.view.toPlainText())

    def refresh(self) -> None:
        if not self.isVisible():
            return
        self._refresh_live()
        bar = self.view.verticalScrollBar()
        pos = bar.value()
        self.view.setHtml(diagnostics_html(self.ctx.engine))
        bar.setValue(pos)

    def _refresh_live(self) -> None:
        eng = self.ctx.engine
        snap = eng.snapshot()
        if snap.preview is None or snap.preview_obs is None:
            return
        from fischmacro.diagnostics.replay import draw
        back = eng.inputs.backend
        recent = [w for t, w, sent, err in list(getattr(back, "recent", []))[-6:] if not w.startswith("move")]
        img = snap.preview.image
        try:
            self.live.set_image(draw(img, eng.profile, snap.preview_obs, eng.fsm, recent, snap.preview.timestamp))
        except Exception:  # noqa: BLE001 - a drawing problem must never break the page
            self.live.set_image(img)
