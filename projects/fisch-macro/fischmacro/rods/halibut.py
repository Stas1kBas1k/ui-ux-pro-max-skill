"""Halibut Harpoon: nothing to press. A fish jump is believed only after 3 frames, so the '!' icon
next to the fish never pulls the bar away."""
from __future__ import annotations



def filter_obs(s, obs: Observation, now: float) -> None:
    """Halibut Harpoon: '!' marks are thin lines like the fish, so a sudden jump of the fish is only
    believed when it is seen in the same place for 3 frames."""
    if s.cfg.kind != "halibut":
        return
    r = obs.reel
    if not r.fish_found:
        return
    if s.fish_trusted is None or abs(r.fish_x - s.fish_trusted) < 0.08:
        s.fish_trusted, s.fish_jump = r.fish_x, None
        return
    x, n = s.fish_jump or (r.fish_x, 0)
    n = n + 1 if abs(r.fish_x - x) < 0.03 else 1
    if n >= 3:
        s.fish_trusted, s.fish_jump = r.fish_x, None
        return
    s.fish_jump = (r.fish_x, n)
    s.ignored_marks += 1
    if s.ignored_marks % 20 == 1:
        s._note(now, f"halibut: ignored a jump to {r.fish_x:.3f} (probably a '!' mark)")
    r.fish_x = s.fish_trusted
