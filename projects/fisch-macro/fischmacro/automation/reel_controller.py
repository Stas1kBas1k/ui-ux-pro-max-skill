"""Feedback controller for the reel minigame.

The catch bar accelerates right while the mouse is held and falls left when it
is released, so the actuator is binary but the plant has inertia. The
controller therefore:

1. smooths fish/bar positions and estimates their velocities across frames;
2. predicts the fish a short time ahead;
3. computes a PD command on the (predicted) fish-to-bar-centre error plus a
   velocity feed-forward term;
4. maps the command to a hold duty cycle around the rod's "hover" duty;
5. turns the duty into hold/release decisions with sigma-delta modulation, so
   fractional duties are realised over consecutive frames;
6. applies edge rules and safety limits (max continuous hold, low confidence).
"""
from __future__ import annotations

from dataclasses import dataclass

from fischmacro.profiles.schema import ReelConfig


@dataclass
class ReelDebug:
    fish_x: float = 0.0
    fish_v: float = 0.0
    predicted: float = 0.0
    bar_center: float = 0.0
    bar_v: float = 0.0
    bar_width: float = 0.0
    error: float = 0.0
    command: float = 0.0
    duty: float = 0.0
    hold: bool = False
    reason: str = ""


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class ReelController:
    def __init__(self, cfg: ReelConfig):
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self._t: float | None = None
        self._fish: float | None = None
        self._bar: float | None = None
        self.fish_v = 0.0
        self.bar_v = 0.0
        self._acc = 0.0
        self._hold = False
        self._hold_since: float | None = None
        self._last_switch = -1e9
        self.debug = ReelDebug()

    def update(self, fish_x: float, bar_left: float, bar_right: float, now: float,
               confidence: float = 1.0, min_switch_interval: float = 0.0) -> bool:
        """Return True if the mouse should be held this frame."""
        c = self.cfg
        bar_c = (bar_left + bar_right) / 2
        bar_w = max(1e-3, bar_right - bar_left)
        dt = 0.0 if self._t is None else max(0.0, now - self._t)
        if self._t is not None and dt > 1e-4:
            a = _clamp(c.smoothing, 0.0, 0.95)
            raw_fv = (fish_x - self._fish) / dt
            raw_bv = (bar_c - self._bar) / dt
            # Clamp single-frame spikes (detection jitter) before smoothing.
            raw_fv = _clamp(raw_fv, -5.0, 5.0)
            raw_bv = _clamp(raw_bv, -5.0, 5.0)
            self.fish_v = a * self.fish_v + (1 - a) * raw_fv
            self.bar_v = a * self.bar_v + (1 - a) * raw_bv
        self._t, self._fish, self._bar = now, fish_x, bar_c

        predicted = _clamp(fish_x + self.fish_v * c.lookahead, 0.0, 1.0)
        error = predicted - bar_c
        # Normalise by bar width so gains transfer between rods with different bar sizes.
        e_n = error / bar_w
        de_n = (self.fish_v - self.bar_v) / bar_w
        command = c.kp * e_n + c.kd * de_n + c.feedforward * self.fish_v / bar_w
        duty = _clamp(c.hold_bias + command, 0.0, 1.0)
        reason = "pd"

        # Edge rules: near a wall the bar should be pinned against it.
        if fish_x <= c.edge_margin and bar_left <= c.edge_margin * 1.5:
            duty, reason = 0.0, "edge-left"
        elif fish_x >= 1 - c.edge_margin and bar_right >= 1 - c.edge_margin * 1.5:
            duty, reason = 1.0, "edge-right"

        if confidence < c.min_confidence:
            duty, reason = 0.0, "low-confidence"

        # Sigma-delta: accumulate the duty and emit hold when it overflows.
        self._acc += duty
        want = self._acc >= 0.5
        if want:
            self._acc -= 1.0
        self._acc = _clamp(self._acc, -1.0, 1.0)
        if duty >= 0.999:
            want = True
        elif duty <= 0.001:
            want = False

        if want and self._hold and self._hold_since is not None and now - self._hold_since >= c.max_hold_seconds:
            want, reason = False, "max-hold"
        if want != self._hold and now - self._last_switch < min_switch_interval:
            want = self._hold
        if want != self._hold:
            self._last_switch = now
            self._hold_since = now if want else None
        self._hold = want

        self.debug = ReelDebug(fish_x, self.fish_v, predicted, bar_c, self.bar_v, bar_w, error,
                               command, duty, want, reason)
        return want

    def release(self) -> None:
        self._hold = False
        self._hold_since = None
        self._acc = 0.0
