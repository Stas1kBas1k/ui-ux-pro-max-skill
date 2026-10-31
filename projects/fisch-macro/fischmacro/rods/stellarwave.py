"""Stellarwave Melody: pick the zodiac signs in order (Aries..Pisces) by clicking them on the reel strip.

Seen in the player's recording: the cursor goes onto the next sign and its star lights up; picked signs
turn white; signs can be anywhere on the strip, inside or outside the bar. The reel itself is "click and
hold anywhere", so the cursor is free: it is kept on the next sign, so the normal reel presses land on it
too, and a short extra tap is made when it arrives. A pick counts when one more star is lit.

States: AIM (move onto the next sign and tap) -> VERIFY (wait for the star) -> AIM. A tap that lit
nothing is retried a little later; a low-confidence match is never clicked.
"""
from __future__ import annotations

VERIFY_S = 0.7      # a star lights up within this time after a good click
RETRY_GAP_S = 0.5


def update(s, obs, now: float) -> None:
    z = obs.zodiac
    if z is None or not z.found:
        return
    if s.stellar_lit is not None and z.lit > s.stellar_lit:
        s.hits += 1
        s._note(now, f"stellar: {z.lit} sign(s) picked")
        s.stellar_state, s.stellar_tries = "AIM", 0
    s.stellar_lit = z.lit
    if s.stellar_state == "VERIFY":
        if now - s.last_fire < VERIFY_S:
            return
        s.misses += 1
        s._note(now, f"stellar: click on {z.next_sign} not counted - retrying")
        s.stellar_state = "AIM"
    if not z.confident:
        return
    # keep the cursor on the next sign (the reel's own presses then pick it as well)
    inp, f = s.fsm.input, s.fsm
    if obs is not None and f.last_obs is not None:
        x, y = f._screen(obs, z.x, z.y)
        if s.stellar_cursor is None or abs(s.stellar_cursor[0] - x) > 6 or abs(s.stellar_cursor[1] - y) > 6:
            inp.move_to(x, y)
            s.stellar_cursor = (x, y)
    if now - s.last_fire < RETRY_GAP_S or s.stellar_tries >= 6:
        return
    s.last_fire = now
    s.stellar_tries += 1
    s.stellar_state = "VERIFY"
    s._note(now, f"stellar: tap {z.next_sign} at ({z.x:.3f}, {z.y:.3f}) score {z.score:.2f}")
    s._act()  # tap where the cursor is, keeping the reel's hold state
