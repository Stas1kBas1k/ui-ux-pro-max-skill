"""Lullaby: click only while the pendulum is over a lit section.

With the real half-moon gauge (player's recording), a hit does not change the lit sections, so the delay is
not learned from them: the click is sent when the pendulum is inside a lit part now and will still be
inside, with a margin, when the click lands (``lead_ms`` ahead). The reel bar is never steered.
"""
from __future__ import annotations

LULLABY_GRACE = 1.2  # seconds after the reel starts during which Lullaby clicks count for nothing


def update(s, obs: Observation, now: float) -> None:
    t = obs.timing
    if not t.present:
        s.pointer_hist.clear()
        return
    s.pointer_hist.append((now, t.pointer))
    gauge = t.source == "gauge"
    if not gauge:
        s._learn_latency(t.segments, now)
    if len(s.pointer_hist) < 2 or not t.segments:
        return
    # Clicks in the first 1.2 s of the reel give nothing in game: wait them out.
    if s.t_start is not None and now - s.t_start < LULLABY_GRACE:
        return
    lead = (max(0.0, s.cfg.lead_ms / 1000.0) + 0.015) if gauge else s.latency
    if gauge:
        _gauge_click(s, t, now, lead)
        return
    if s.fired_segment is not None:
        a, b = s.fired_segment
        if a - 0.02 <= t.pointer <= b + 0.02:
            return  # a second click in the same section does nothing - wait for the next one
        s.fired_segment = None
    predicted = s._predict(t.pointer, now, lead)
    # Fire when the click will land inside a lit section. (The test game's simplified metronome: its delay is
    # learned from sections changing after a hit, which needs a short pause between hits.)
    if now - s.last_fire < max(s.cfg.min_interval, 0.25):
        return
    for a, b in t.segments:
        # inside, with a margin, when the click lands: a miss costs 5% progress, a skipped beat nothing
        margin = max(0.008, min(0.02, (b - a) * 0.15))
        if a + margin <= predicted <= b - margin:
            s.last_fire = now
            s.fired_segment = (a, b)
            s._act()
            s._click_at, s._click_segments = now, list(t.segments)
            return


def _gauge_click(s, t, now: float, lead: float) -> None:
    """The real half-moon: one click on every pass of the pendulum over every lit part, aimed at the middle
    of the part. A pass ends when the pendulum leaves the part or turns around (a lit part at the end of the
    swing is passed twice: out and back). No pause between clicks beyond that."""
    v = s._velocity()
    # direction only from a real swing (2-5 /s); a reading that wobbles by a few thousandths is not a turn
    direction = 0 if abs(v) < 0.8 else (1 if v > 0 else -1)
    if s.fired_segment is not None:
        a, b = s.fired_segment
        left = not (a - 0.02 <= t.pointer <= b + 0.02)
        turned = direction != 0 and s.fired_dir != 0 and direction != s.fired_dir
        if not (left or turned):
            return  # already clicked on this pass
        s.fired_segment = None
    if now - s.last_fire < s.cfg.min_interval:
        return
    h = s.pointer_hist
    dt = max(0.005, min(0.1, h[-1][0] - h[-2][0]))  # time to the next frame
    pred = s._predict(t.pointer, now, lead)            # where the click will land if sent now
    pred_next = s._predict(t.pointer, now, lead + dt)  # ... if sent on the next frame
    for a, b in t.segments:
        m = max(0.015, min(0.04, (b - a) * 0.1))
        lo, hi = a + m, b - m
        if not (lo <= pred <= hi and lo - 0.03 <= t.pointer <= hi + 0.03):
            continue
        c = (a + b) / 2
        at_middle = (pred - c) * (pred_next - c) <= 0 or abs(pred - c) <= 0.01
        last_chance = not (lo <= pred_next <= hi)  # next frame would land outside: now or never
        # a lit part at the end of the swing: the pendulum turns around before its middle - click near the turn
        turning = abs(pred_next - pred) < 0.004
        if at_middle or last_chance or turning:
            s.last_fire = now
            s.fired_segment, s.fired_dir = (a, b), direction
            s._act()
            s._click_at, s._click_segments = now, list(t.segments)
            return
