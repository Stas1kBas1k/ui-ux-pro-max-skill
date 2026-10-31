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
        # Stellarwave state machine: AIM -> VERIFY -> (target changed: hit) AIM / (no change: miss) AIM
        self.stellar_state = "AIM"
        self.stellar_rejected: list[float] = []  # x of signs already tried (wrong) for the current target
        self.stellar_tries = 0
        self.hits = 0
        self.misses = 0
        # MiguRod: one press per timing bar
        self.migu_fired = False
        self.migu_seen_at: float | None = None
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
        if c.kind == "lullaby":
            self._lullaby(obs, now)
        elif c.kind == "migu":
            self._migu(obs, now)
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

    def _note(self, now: float, msg: str) -> None:
        self.log.append(f"{now:9.2f} {msg}")

    def _stellar(self, obs: Observation, now: float) -> None:
        """Click the sign on the bar that matches the one asked for, then check the click worked: the sign
        asked for changes after a correct click. A wrong click marks that sign and the next best one is
        tried; after 3 tries the target is left alone until it changes (no spamming)."""
        m = obs.match
        if not m.target_present or len(m.options) < 2:
            if self.stellar_state == "VERIFY" and now - self.last_fire > 0.9:
                self.stellar_state = "AIM"
            return
        if self.stellar_state == "VERIFY":
            if m.signature != self.done_signature:
                self.hits += 1
                self._note(now, f"stellar hit ({self.hits})")
                self.stellar_state, self.stellar_rejected, self.stellar_tries = "AIM", [], 0
            elif now - self.last_fire >= 0.6:
                self.misses += 1
                self._note(now, f"stellar miss at x={self.stellar_rejected[-1]:.3f}")
                self.stellar_state = "AIM" if self.stellar_tries < 3 else "GAVE_UP"
            else:
                return
        if self.stellar_state == "GAVE_UP":
            if m.signature == self.done_signature:
                return
            self.stellar_state, self.stellar_rejected, self.stellar_tries = "AIM", [], 0
        if m.signature != self.done_signature:
            self.stellar_rejected, self.stellar_tries = [], 0
        if now - self.last_fire < self.cfg.min_interval:
            return
        options = [o for o in m.options if all(abs(o.x - x) > 0.01 for x in self.stellar_rejected)]
        if not options:
            return
        best = max(options, key=lambda o: o.score)
        # near ties (similar-looking signs) are fine: the click is checked, and a wrong one is not repeated
        if best.score >= self.cfg.match_threshold:
            self.last_fire = now
            self.done_signature = m.signature
            self.stellar_rejected.append(best.x)
            self.stellar_tries += 1
            self.stellar_state = "VERIFY"
            self._act((best.x, best.y))

    def _migu(self, obs: Observation, now: float) -> None:
        """MiguRod timing bar: press the key once, when the pointer will be in the middle."""
        t = obs.timing
        if not t.present:
            if self.migu_seen_at is not None:
                self._note(now, "migu bar gone" + (" after press" if self.migu_fired else " (not pressed)"))
            self.migu_seen_at, self.migu_fired = None, False
            self.pointer_hist.clear()
            return
        if self.migu_seen_at is None:
            self.migu_seen_at = now
            self._note(now, "migu timing bar")
        self.pointer_hist.append((now, t.pointer))
        if self.migu_fired or len(self.pointer_hist) < 3:
            return
        centre = 0.5
        if t.segments:  # a drawn centre zone, if one is found near the middle
            a, b = min(t.segments, key=lambda s: abs((s[0] + s[1]) / 2 - 0.5))
            if abs((a + b) / 2 - 0.5) < 0.15:
                centre = (a + b) / 2
        ahead = self._predict(t.pointer, now, self.latency)
        if abs(ahead - centre) <= self.cfg.migu_window * 0.6:
            self.migu_fired = True
            self.fsm.input.press_key(self.cfg.migu_key or "shift")
            self.actions += 1
            self._note(now, f"migu press at {t.pointer:.3f} (aimed {ahead:.3f})")

    def filter_obs(self, obs: Observation, now: float) -> None:
        """Halibut Harpoon: '!' marks are thin lines like the fish, so a sudden jump of the fish is only
        believed when it is seen in the same place for 3 frames."""
        if self.cfg.kind != "halibut":
            return
        r = obs.reel
        if not r.fish_found:
            return
        if self.fish_trusted is None or abs(r.fish_x - self.fish_trusted) < 0.08:
            self.fish_trusted, self.fish_jump = r.fish_x, None
            return
        x, n = self.fish_jump or (r.fish_x, 0)
        n = n + 1 if abs(r.fish_x - x) < 0.03 else 1
        if n >= 3:
            self.fish_trusted, self.fish_jump = r.fish_x, None
            return
        self.fish_jump = (r.fish_x, n)
        self.ignored_marks += 1
        if self.ignored_marks % 20 == 1:
            self._note(now, f"halibut: ignored a jump to {r.fish_x:.3f} (probably a '!' mark)")
        r.fish_x = self.fish_trusted

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
