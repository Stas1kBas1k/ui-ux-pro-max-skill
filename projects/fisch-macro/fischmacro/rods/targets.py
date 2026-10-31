"""Generic coloured-target clicker (experimental, for rods that need clicking marked spots)."""
from __future__ import annotations

import math


def update(s, obs: Observation, now: float) -> None:
    if now - s.last_fire < s.cfg.target_interval:
        return
    s.recent = [r for r in s.recent if now - r[2] < 0.5]
    for x, y in obs.targets.targets:
        if any(math.hypot(x - rx, y - ry) < 0.02 for rx, ry, _ in s.recent):
            continue
        s.last_fire = now
        s.recent.append((x, y, now))
        s._act((x, y))
        return
