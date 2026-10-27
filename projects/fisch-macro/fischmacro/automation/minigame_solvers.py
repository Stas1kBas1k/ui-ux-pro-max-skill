"""Solvers for rod-specific minigames, run every frame while reeling.

They act through the same InputController as everything else, so the kill
switch, pause and focus guard apply to them too.
"""
from __future__ import annotations

import math
from collections import deque

from fischmacro.profiles.schema import MinigameConfig
from fischmacro.vision.engine import Observation


class MinigameSolver:
    def __init__(self, cfg: MinigameConfig, fsm):
        self.cfg = cfg
        self.fsm = fsm
        self.reset()

    def reset(self) -> None:
        self.started = False
        self.last_fire = -1e9
        self.pointer_hist: deque[tuple[float, float]] = deque(maxlen=6)
        self.done_signature: int | None = None
        self.recent: list[tuple[float, float, float]] = []
        self.actions = 0

    # -- input helpers
    def _act(self, pos: tuple[float, float] | None = None) -> None:
        """Perform the minigame input, keeping the reel's hold state as it was."""
        inp = self.fsm.input
        action = (self.cfg.action or "click").strip().lower()
        self.actions += 1
        if action != "click":
            inp.press_key(action)
            return
        obs = self.fsm.last_obs
        held = inp.is_held()
        if pos is not None and obs is not None:
            x, y = self.fsm._screen(obs, *pos)
            inp.move_to(x, y)
        if held:
            inp.mouse_up()
            inp.mouse_down()
        else:
            inp.mouse_down()
            inp.mouse_up()
        if pos is not None and self.cfg.neutral_after_click and obs is not None:
            inp.move_to(*self.fsm._screen(obs, 0.5, 0.45))

    # -- per frame
    def update(self, obs: Observation, now: float) -> None:
        c = self.cfg
        if not self.started:
            self.started = True
            for _ in range(c.mode_presses if c.kind == "lullaby" else 0):
                self.fsm.input.press_key(c.mode_key)
        if c.kind == "lullaby":
            self._lullaby(obs, now)
        elif c.kind == "stellarwave":
            self._stellar(obs, now)
        elif c.kind == "targets":
            self._targets(obs, now)

    def _lullaby(self, obs: Observation, now: float) -> None:
        t = obs.timing
        if not t.present:
            self.pointer_hist.clear()
            return
        self.pointer_hist.append((now, t.pointer))
        if len(self.pointer_hist) < 2 or not t.segments:
            return
        (t0, x0), (t1, x1) = self.pointer_hist[-2], self.pointer_hist[-1]
        v = (x1 - x0) / max(1e-3, t1 - t0)
        lead = self.cfg.lead_ms / 1000.0
        predicted = t.pointer + v * lead
        # Fire while both now and the predicted moment are inside the same lit section.
        if now - self.last_fire < self.cfg.min_interval:
            return
        for a, b in t.segments:
            margin = min(0.01, (b - a) * 0.15)
            if a + margin <= predicted <= b - margin and a - 0.02 <= t.pointer <= b + 0.02:
                self.last_fire = now
                self._act()
                return

    def _stellar(self, obs: Observation, now: float) -> None:
        m = obs.match
        if not m.target_present or len(m.options) < 2:
            return
        if m.signature == self.done_signature and now - self.last_fire < 1.5:
            return  # already answered this sign
        if now - self.last_fire < self.cfg.min_interval:
            return
        best = m.best
        ranked = sorted((o.score for o in m.options), reverse=True)
        clear_winner = len(ranked) < 2 or ranked[0] - ranked[1] > 0.08
        if best is not None and best.score >= self.cfg.match_threshold and clear_winner:
            self.last_fire = now
            self.done_signature = m.signature
            self._act((best.x, best.y))

    def _targets(self, obs: Observation, now: float) -> None:
        if now - self.last_fire < self.cfg.target_interval:
            return
        self.recent = [r for r in self.recent if now - r[2] < 0.5]
        for x, y in obs.targets.targets:
            if any(math.hypot(x - rx, y - ry) < 0.02 for rx, ry, _ in self.recent):
                continue
            self.last_fire = now
            self.recent.append((x, y, now))
            self._act((x, y))
            return
