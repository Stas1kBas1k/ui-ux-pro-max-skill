"""Stellarwave Melody sign clicker (AIM -> VERIFY state machine). Off by default: how a sign is
picked in game is not confirmed (see docs/REPAIR_REPORT.md)."""
from __future__ import annotations



def update(s, obs: Observation, now: float) -> None:
    """Click the sign on the bar that matches the one asked for, then check the click worked: the sign
    asked for changes after a correct click. A wrong click marks that sign and the next best one is
    tried; after 3 tries the target is left alone until it changes (no spamming)."""
    m = obs.match
    if not m.target_present or len(m.options) < 2:
        if s.stellar_state == "VERIFY" and now - s.last_fire > 0.9:
            s.stellar_state = "AIM"
        return
    if s.stellar_state == "VERIFY":
        if m.signature != s.done_signature:
            s.hits += 1
            s._note(now, f"stellar hit ({s.hits})")
            s.stellar_state, s.stellar_rejected, s.stellar_tries = "AIM", [], 0
        elif now - s.last_fire >= 0.6:
            s.misses += 1
            s._note(now, f"stellar miss at x={s.stellar_rejected[-1]:.3f}")
            s.stellar_state = "AIM" if s.stellar_tries < 3 else "GAVE_UP"
        else:
            return
    if s.stellar_state == "GAVE_UP":
        if m.signature == s.done_signature:
            return
        s.stellar_state, s.stellar_rejected, s.stellar_tries = "AIM", [], 0
    if m.signature != s.done_signature:
        s.stellar_rejected, s.stellar_tries = [], 0
    if now - s.last_fire < s.cfg.min_interval:
        return
    options = [o for o in m.options if all(abs(o.x - x) > 0.01 for x in s.stellar_rejected)]
    if not options:
        return
    best = max(options, key=lambda o: o.score)
    # near ties (similar-looking signs) are fine: the click is checked, and a wrong one is not repeated
    if best.score >= s.cfg.match_threshold:
        s.last_fire = now
        s.done_signature = m.signature
        s.stellar_rejected.append(best.x)
        s.stellar_tries += 1
        s.stellar_state = "VERIFY"
        s._act((best.x, best.y))
