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

import numpy as np

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
    hover: float = 0.5
    hover_learned: bool = False


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class HoverEstimator:
    """Online estimate of the hover duty from (hold, bar acceleration) samples.

    Bar acceleration is modelled as ``a = alpha * hold + beta``; the duty that
    gives zero mean acceleration is ``-beta / alpha``. Sums decay exponentially
    so the estimate follows the current rod.
    """

    def __init__(self, forget: float = 0.997, min_samples: float = 40.0):
        self.forget = forget
        self.min_samples = min_samples
        self.n = self.sh = self.shh = self.sa = self.sah = 0.0
        self.value: float | None = None

    def add(self, hold: float, accel: float) -> None:
        f = self.forget
        self.n = f * self.n + 1.0
        self.sh = f * self.sh + hold
        self.shh = f * self.shh + hold * hold
        self.sa = f * self.sa + accel
        self.sah = f * self.sah + accel * hold
        if self.n < self.min_samples:
            return
        mh, ma = self.sh / self.n, self.sa / self.n
        var = self.shh / self.n - mh * mh
        if var < 0.04 or not (0.1 < mh < 0.9):  # need both held and released samples
            return
        alpha = (self.sah / self.n - mh * ma) / var
        if alpha <= 0.05:
            return
        estimate = _clamp(-(ma - alpha * mh) / alpha, 0.1, 0.9)
        self.value = estimate if self.value is None else 0.9 * self.value + 0.1 * estimate


class PlantModel:
    """Online model of the catch bar: ``accel = alpha * hold + beta + gamma * velocity``.

    Fitted by exponentially-forgotten least squares from what the bar actually
    did. ``alpha`` is the push while holding, ``beta`` the fall when released,
    ``gamma`` the drag. Used by precision mode to simulate the next moments.
    """

    def __init__(self, forget: float = 0.996, min_samples: float = 60.0):
        self.forget = forget
        self.min_samples = min_samples
        self.xx = np.zeros((3, 3))
        self.xa = np.zeros(3)
        self.n = 0.0
        self.params: tuple[float, float, float] | None = None

    def add(self, hold: float, velocity: float, accel: float) -> None:
        x = np.array([hold, 1.0, velocity])
        self.xx = self.forget * self.xx + np.outer(x, x)
        self.xa = self.forget * self.xa + x * accel
        self.n = self.forget * self.n + 1.0
        if self.n < self.min_samples:
            return
        try:
            alpha, beta, gamma = np.linalg.solve(self.xx + np.eye(3) * 1e-3, self.xa)
        except np.linalg.LinAlgError:
            return
        if alpha > 0.2 and beta < alpha and -20 < gamma <= 0.5:
            self.params = (float(alpha), float(beta), float(min(0.0, gamma)))

    @property
    def ready(self) -> bool:
        return self.params is not None


class ReelController:
    def __init__(self, cfg: ReelConfig):
        self.cfg = cfg
        self.hover = HoverEstimator()  # kept across minigames: the rod does not change mid-session
        self.plant = PlantModel()
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
        self._raw_bv: float | None = None
        self._prev_hold = False  # decision before the last one
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
            # Learn hover duty from the input applied during the last interval, away from the walls.
            # Skip samples near the walls and while the fish icon overlaps a bar edge (that shifts
            # the detected edge by the icon width and fakes a velocity jump).
            near_edge = min(abs(fish_x - bar_left), abs(fish_x - bar_right)) < 0.03
            if self._raw_bv is not None and bar_left > 0.03 and bar_right < 0.97 and not near_edge:
                accel = (raw_bv - self._raw_bv) / dt
                if abs(accel) < 25.0:
                    self.hover.add(1.0 if self._hold else 0.0, accel)
                    # The two velocity samples straddle the last two decisions, so the input is their
                    # average; the midpoint velocity keeps noise uncorrelated with the acceleration.
                    h_mix = (float(self._hold) + float(self._prev_hold)) / 2
                    self.plant.add(h_mix, (raw_bv + self._raw_bv) / 2, accel)
            self._raw_bv = raw_bv
        self._t, self._fish, self._bar = now, fish_x, bar_c

        predicted = _clamp(fish_x + self.fish_v * c.lookahead, 0.0, 1.0)
        error = predicted - bar_c
        # Normalise by bar width so gains transfer between rods with different bar sizes.
        e_n = error / bar_w
        de_n = (self.fish_v - self.bar_v) / bar_w
        command = c.kp * e_n + c.kd * de_n + c.feedforward * self.fish_v / bar_w
        bias = self.hover.value if (c.auto_hover and self.hover.value is not None) else c.hold_bias
        duty = _clamp(bias + command, 0.0, 1.0)
        reason = "pd"

        # Edge rules: near a wall the bar should be pinned against it.
        if fish_x <= c.edge_margin and bar_left <= c.edge_margin * 1.5:
            duty, reason = 0.0, "edge-left"
        elif fish_x >= 1 - c.edge_margin and bar_right >= 1 - c.edge_margin * 1.5:
            duty, reason = 1.0, "edge-right"

        precision = c.mode == "precision" and self.plant.ready
        if precision and reason == "pd":
            hold_now = self._plan(fish_x, self.fish_v, bar_c, self.bar_v, bar_w)
            duty, reason = (1.0 if hold_now else 0.0), "mpc"

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
        self._prev_hold = self._hold
        self._hold = want

        self.debug = ReelDebug(fish_x, self.fish_v, predicted, bar_c, self.bar_v, bar_w, error,
                               command, duty, want, reason, bias, c.auto_hover and self.hover.value is not None)
        return want

    # 16 hold/release plans over 4 segments, as a (16, 4) array of 0/1
    _PLANS = np.array([[(i >> k) & 1 for k in range(3, -1, -1)] for i in range(16)], dtype=float)

    def _plan(self, fish: float, fish_v: float, bar: float, bar_v: float, width: float) -> bool:
        """Model-predictive choice: simulate every plan and keep the fish centred in the bar."""
        alpha, beta, gamma = self.plant.params
        c = self.cfg
        steps_per_seg = 6
        dt = c.mpc_horizon / (4 * steps_per_seg)
        n = len(self._PLANS)
        pos = np.full(n, bar)
        vel = np.full(n, bar_v)
        f, fv = fish, fish_v
        lo, hi = width / 2, 1 - width / 2
        inner = width * (0.5 - c.mpc_margin)  # fish should stay this close to the bar centre
        cost = np.zeros(n)
        for seg in range(4):
            hold = self._PLANS[:, seg]
            for _ in range(steps_per_seg):
                vel = vel + (alpha * hold + beta + gamma * vel) * dt
                pos = pos + vel * dt
                hit = (pos < lo) | (pos > hi)
                pos = np.clip(pos, lo, hi)
                vel = np.where(hit, 0.0, vel)
                f = min(1.0, max(0.0, f + fv * dt))
                fv *= 0.97  # fish velocity predictions fade
                err = np.abs(f - pos)
                cost += np.maximum(0.0, err - inner) ** 2 * 400 + err ** 2
        return bool(self._PLANS[int(np.argmin(cost)), 0])

    def release(self) -> None:
        self._hold = False
        self._hold_since = None
        self._acc = 0.0
