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
    if s.fired_segment is not None:
        a, b = s.fired_segment
        if a - 0.02 <= t.pointer <= b + 0.02:
            return  # a second click in the same section does nothing - wait for the next one
        s.fired_segment = None
    lead = (max(0.0, s.cfg.lead_ms / 1000.0) + 0.015) if gauge else s.latency
    predicted = s._predict(t.pointer, now, lead)
    # Fire when the click will land inside a lit section.
    if now - s.last_fire < s.cfg.min_interval:
        return
    for a, b in t.segments:
        # inside, with a margin, when the click lands: a miss costs 5% progress, a skipped beat nothing
        margin = max(0.008, min(0.02, (b - a) * 0.15)) if not gauge else max(0.03, min(0.06, (b - a) * 0.12))
        now_inside = (a + margin <= t.pointer <= b - margin) if gauge else True
        if now_inside and a + margin <= predicted <= b - margin:
            s.last_fire = now
            s.fired_segment = (a, b)
            s._act()
            s._click_at, s._click_segments = now, list(t.segments)
            return
