"""Fish and catch-bar tracking between detections.

Detections are per frame and sometimes wrong or missing: the fish marker crosses a bar edge, a zodiac
glyph or a Halibut "!" looks like a line, a frame is dropped. Steering directly on raw detections made
the bar let go whenever one frame was missed and jump whenever one frame was wrong.

``ReelTracker`` keeps a position + velocity estimate for the fish and for the bar (alpha-beta filters,
the steady-state form of a Kalman filter for constant-velocity motion):

* a detection far from where the fish should be is treated as an outlier until it is seen in the same
  place on 3 frames in a row (then it is real: the fish really jumped);
* a sudden direction change shows up as large residuals; the filter then trusts new measurements more
  (manoeuvre adaptation) so it does not lag behind a fish that turned;
* with no detection, the estimate coasts on its velocity for a short time with falling confidence,
  then the track is declared lost (the caller releases input instead of guessing).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Track1D:
    x: float = 0.0
    v: float = 0.0
    t: float | None = None
    alpha: float = 0.6        # position gain
    beta: float = 0.25        # velocity gain
    gate: float = 0.10        # residual (fraction of the track) beyond which a measurement is suspicious
    confirm: int = 3          # frames a far-away measurement must repeat before it is believed
    residual: float = 0.0     # smoothed |residual|, for manoeuvre detection
    _jump_x: float | None = None
    _jump_n: int = 0

    @property
    def started(self) -> bool:
        return self.t is not None

    def predict(self, now: float) -> float:
        if self.t is None:
            return self.x
        return min(1.0, max(0.0, self.x + self.v * max(0.0, now - self.t)))

    def reset(self) -> None:
        self.t, self.v, self.residual, self._jump_x, self._jump_n = None, 0.0, 0.0, None, 0

    def update(self, z: float, now: float) -> bool:
        """Fold in a measurement. Returns False when it was rejected as an outlier."""
        if self.t is None:
            self.x, self.v, self.t = z, 0.0, now
            return True
        dt = max(1e-3, now - self.t)
        pred = self.x + self.v * dt
        r = z - pred
        gate = self.gate + abs(self.v) * dt
        if abs(r) > gate:
            if self._jump_x is not None and abs(z - self._jump_x) < 0.03:
                self._jump_n += 1
            else:
                self._jump_x, self._jump_n = z, 1
            if self._jump_n < self.confirm:
                # coast instead: keep the old track for this frame
                self.x, self.t = min(1.0, max(0.0, pred)), now
                return False
            # the fish really is there: restart the track at the new place
            self.x, self.v, self.t, self.residual = z, 0.0, now, 0.0
            self._jump_x, self._jump_n = None, 0
            return True
        self._jump_x, self._jump_n = None, 0
        self.residual = 0.7 * self.residual + 0.3 * abs(r)
        # manoeuvre: when residuals stay large (turn, sudden acceleration) trust the measurement more
        boost = min(1.0, self.residual / 0.02)
        a = self.alpha + (0.95 - self.alpha) * boost
        b = self.beta + (0.6 - self.beta) * boost
        self.x = pred + a * r
        self.v = max(-6.0, min(6.0, self.v + b * r / dt))
        self.t = now
        return True


@dataclass
class TrackState:
    usable: bool = False
    fish_x: float = 0.0
    fish_v: float = 0.0
    bar_left: float = 0.0
    bar_right: float = 0.0
    bar_v: float = 0.0
    confidence: float = 0.0
    coasting: bool = False
    lost_for: float = 0.0
    rejected: int = 0          # outliers ignored in this reel

    @property
    def direction(self) -> str:
        return "right" if self.fish_v > 0.05 else "left" if self.fish_v < -0.05 else "steady"


class ReelTracker:
    def __init__(self, max_coast: float = 0.3):
        self.max_coast = max_coast
        self.reset()

    def reset(self) -> None:
        self.fish = Track1D()
        self.bar = Track1D(alpha=0.7, beta=0.3, gate=0.15, confirm=2)
        self.bar_w = 0.0
        self.last_fish_seen: float | None = None
        self.last_bar_seen: float | None = None
        self.state = TrackState()

    def update(self, reel, now: float, min_conf: float = 0.5) -> TrackState:
        """``reel`` is a vision ReelResult. Returns the filtered state (also kept in ``self.state``)."""
        s = self.state
        fish_ok = reel.fish_found and reel.fish_confidence >= min_conf
        bar_ok = reel.bar_found and reel.bar_confidence >= min_conf and reel.bar_right > reel.bar_left
        accepted = False
        if fish_ok:
            accepted = self.fish.update(reel.fish_x, now)
            if accepted:
                self.last_fish_seen = now
            else:
                s.rejected += 1
        if bar_ok:
            c, w = (reel.bar_left + reel.bar_right) / 2, reel.bar_right - reel.bar_left
            if self.bar.update(c, now):
                self.last_bar_seen = now
                self.bar_w = w if self.bar_w == 0 else 0.7 * self.bar_w + 0.3 * w
        out = TrackState(rejected=s.rejected)
        if not self.fish.started or self.last_fish_seen is None:
            self.state = out
            return out
        lost_for = now - self.last_fish_seen
        out.lost_for = lost_for
        if lost_for > self.max_coast:
            self.state = out  # lost: the caller must not steer on a guess
            return out
        out.coasting = not accepted
        out.fish_x = self.fish.predict(now) if out.coasting else self.fish.x
        out.fish_v = self.fish.v
        conf = reel.fish_confidence if accepted else 0.9 * (1 - lost_for / self.max_coast)
        bar_fresh = self.last_bar_seen is not None and now - self.last_bar_seen <= self.max_coast
        if bar_fresh and self.bar_w > 0:
            bc = self.bar.predict(now)
            out.bar_left, out.bar_right, out.bar_v = bc - self.bar_w / 2, bc + self.bar_w / 2, self.bar.v
        else:
            conf = min(conf, 0.4)  # fish only: usable for fish-only steering, not for the full controller
        out.confidence = max(0.0, min(1.0, conf))
        out.usable = True
        self.state = out
        return out
