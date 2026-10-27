"""Solvers for rod-specific minigames, run every frame while reeling.

They act through the same InputController as everything else, so the kill
switch, pause and focus guard apply to them too.
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np

from fischmacro.profiles.schema import MinigameConfig
from fischmacro.vision.engine import Observation

LULLABY_GRACE = 1.2
LATENCY_SCAN = (0.07, 0.03, 0.10, 0.05, 0.13, 0.02, 0.16)  # delays tried until a hit is seen  # seconds after the reel starts during which Lullaby clicks count for nothing


class MinigameSolver:
    def __init__(self, cfg: MinigameConfig, fsm):
        self.cfg = cfg
        self.fsm = fsm
        # delay from the frame we decide on to the click landing in game; learned from hits, kept across catches
        self.latency = max(0.0, cfg.lead_ms / 1000.0) + 0.015
        self.latency_samples = 0
        self.miss_streak = 0
        self._scan_i = 0
        self.reset()

    def reset(self) -> None:
        self.started = False
        self.last_fire = -1e9
        self.pointer_hist: deque[tuple[float, float]] = deque(maxlen=6)
        self.done_signature: int | None = None
        self.recent: list[tuple[float, float, float]] = []
        self.actions = 0
        self.t_start: float | None = None
        self.frame_dt = 0.03  # measured time between frames
        self._click_at: float | None = None
        self._click_segments: list = []
        self._last_now: float | None = None
        self.fired_segment: tuple[float, float] | None = None  # Lullaby: section already clicked this pass

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

    def press_allowed(self, obs: Observation, now: float) -> bool:
        """Lullaby counts every mouse press as a beat: a press outside a lit section is a miss (-5% progress).
        So the reel may only start a new press while the pendulum is over a lit section."""
        if self.cfg.kind != "lullaby" or (self.cfg.action or "click").strip().lower() != "click":
            return True
        t = obs.timing
        if not t.present or not t.segments:
            return False
        # (no exception for the first 1.2 s: we see the reel start a little late, so that window is unsure)
        # where the pendulum will be when the press lands
        ahead = self._predict(t.pointer, now, self.latency)
        return any(a + 0.01 <= t.pointer <= b - 0.01 and a + 0.01 <= ahead <= b - 0.01 for a, b in t.segments)

    def _learn_latency(self, segments, now: float) -> None:
        """A hit changes the lit sections. The time from our click decision to that change is the real
        delay of this PC + Roblox, so the next clicks aim that far ahead (instead of a fixed guess)."""
        if self._click_at is None:
            return
        age = now - self._click_at
        if age > 0.4:
            # no visible change: a miss. Two in a row (or any before the first hit) means the delay guess
            # is off, so try the next one; misses are cheap compared with never hitting at all.
            self._click_at = None
            self.miss_streak += 1
            if self.latency_samples == 0 or self.miss_streak >= 3:
                self.latency = LATENCY_SCAN[self._scan_i % len(LATENCY_SCAN)]
                self._scan_i += 1
                self.miss_streak = 0
            return
        old = self._click_segments
        changed = len(old) != len(segments) or any(abs(a - c) > 0.02 or abs(b - d) > 0.02
                                                  for (a, b), (c, d) in zip(sorted(old), sorted(segments)))
        if changed:
            measured = min(0.25, max(0.0, age - self.frame_dt / 2))
            self.latency = measured if self.latency_samples == 0 else 0.7 * self.latency + 0.3 * measured
            self.latency_samples += 1
            self.miss_streak = 0
            self._click_at = None

    def _predict(self, x_now: float, now: float, ahead: float) -> float:
        """Where the pendulum will be ``ahead`` seconds from now. It swings and slows down at the ends,
        so fit a curve through the last few positions instead of a straight line."""
        pts = list(self.pointer_hist)[-5:]
        if len(pts) >= 4 and ahead > 0.075:
            ts = np.array([p[0] - now for p in pts])
            xs = np.array([p[1] for p in pts])
            try:
                a, b, c = np.polyfit(ts, xs, 2)
                return float(a * ahead * ahead + b * ahead + x_now)
            except (np.linalg.LinAlgError, ValueError):
                pass
        return x_now + self._velocity() * ahead

    def _velocity(self) -> float:
        if len(self.pointer_hist) < 2:
            return 0.0
        (t0, x0), (t1, x1) = self.pointer_hist[-2], self.pointer_hist[-1]
        return (x1 - x0) / max(1e-3, t1 - t0)

    # -- per frame
    def update(self, obs: Observation, now: float) -> None:
        c = self.cfg
        if self._last_now is not None and 0 < now - self._last_now < 0.2:
            self.frame_dt = 0.8 * self.frame_dt + 0.2 * (now - self._last_now)
        self._last_now = now
        if not self.started:
            self.started = True
            self.t_start = now
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
        self._learn_latency(t.segments, now)
        if len(self.pointer_hist) < 2 or not t.segments:
            return
        # Clicks in the first 1.2 s of the reel give nothing in game: wait them out.
        if self.t_start is not None and now - self.t_start < LULLABY_GRACE:
            return
        if self.fired_segment is not None:
            a, b = self.fired_segment
            if a - 0.02 <= t.pointer <= b + 0.02:
                return  # a second click in the same section does nothing - wait for the next one
            self.fired_segment = None
        predicted = self._predict(t.pointer, now, self.latency)
        # Fire when the click will land inside a lit section.
        if now - self.last_fire < self.cfg.min_interval:
            return
        for a, b in t.segments:
            # inside, with a margin, when the click lands: a miss costs 5% progress, a skipped beat nothing
            margin = max(0.008, min(0.02, (b - a) * 0.15))
            if a + margin <= predicted <= b - margin:
                self.last_fire = now
                self.fired_segment = (a, b)
                self._act()
                self._click_at, self._click_segments = now, list(t.segments)
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
