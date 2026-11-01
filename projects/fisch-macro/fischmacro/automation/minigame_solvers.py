"""Solvers for rod-specific minigames, run every frame while reeling.

They act through the same InputController as everything else, so the kill
switch, pause and focus guard apply to them too.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from fischmacro.profiles.schema import MinigameConfig
from fischmacro.rods import ROD_BEHAVIOURS
from fischmacro.rods.lullaby import LULLABY_GRACE  # noqa: F401 - kept importable from here
from fischmacro.vision.engine import Observation

LATENCY_SCAN = (0.07, 0.03, 0.10, 0.05, 0.13, 0.02, 0.16)  # delays tried until a hit is seen


class MinigameSolver:
    def __init__(self, cfg: MinigameConfig, fsm):
        self.cfg = cfg
        self.fsm = fsm
        # delay from the frame we decide on to the click landing in game; learned from hits, kept across catches
        self.latency = max(0.0, cfg.lead_ms / 1000.0) + 0.015
        self.latency_samples = 0
        self.miss_streak = 0
        self._scan_i = 0
        from fischmacro.rods.prompts import PromptReader
        self.prompts = PromptReader(allowed={"shift", "space", "ctrl", "alt"})  # keys a prompt may ask for
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
        self.fired_dir = 0  # Lullaby: pendulum direction when it was clicked (a turn starts a new pass)
        self.special_logged = False  # rods/special.py: logged once per catch
        # Stellarwave state machine: AIM -> VERIFY -> (target changed: hit) AIM / (no change: miss) AIM
        self.stellar_state = "AIM"
        self.stellar_lit: int | None = None
        self.stellar_cursor: tuple[int, int] | None = None
        self.stellar_rejected: list[float] = []  # x of signs already tried (wrong) for the current target
        self.stellar_tries = 0
        self.hits = 0
        self.misses = 0
        # MiguRod: one press per timing bar
        self.migu_fired: float | None = None   # time of the press for the current bar
        self.migu_seen_at: float | None = None
        self.migu_retries = 0
        # Halibut: last trusted fish position and a candidate jump waiting for confirmation
        self.fish_trusted: float | None = None
        self.fish_jump: tuple[float, int] | None = None
        self.ignored_marks = 0
        self.log: deque[str] = deque(maxlen=40)

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
        behaviour = ROD_BEHAVIOURS.get(c.kind)
        announced = self.fsm.__dict__.setdefault("announced", set())
        if behaviour is not None and c.kind != "none" and c.kind not in announced:
            announced.add(c.kind)  # once per run: the log shows which special rod handler ran
            emit = getattr(self.fsm, "emit", None)
            if emit is not None:
                emit("special", f"Special rod handler active: {behaviour.label}")
        if behaviour is not None and behaviour.update is not None:
            behaviour.update(self, obs, now)

    def filter_obs(self, obs: Observation, now: float) -> None:
        behaviour = ROD_BEHAVIOURS.get(self.cfg.kind)
        if behaviour is not None and behaviour.filter_obs is not None:
            behaviour.filter_obs(self, obs, now)

    def _note(self, now: float, msg: str) -> None:
        self.log.append(f"{now:9.2f} {msg}")


