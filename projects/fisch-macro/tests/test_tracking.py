"""Fish / bar tracking between detections: direction, turns, dropouts, false detections, bar sizes."""
import math

import pytest

from fischmacro.automation.tracking import ReelTracker, Track1D
from fischmacro.vision.detectors import ReelResult

DT = 1 / 40


def reel(fish=None, bar=None, conf=1.0):
    r = ReelResult()
    r.ui_present = True
    if fish is not None:
        r.fish_found, r.fish_x, r.fish_confidence = True, fish, conf
    if bar is not None:
        r.bar_found, r.bar_left, r.bar_right, r.bar_confidence = True, bar[0], bar[1], conf
    return r


@pytest.mark.parametrize("speed", [0.3, -0.3, 0.6, -0.6])
def test_follows_a_fish_moving_left_or_right(speed):
    tr = Track1D()
    x = 0.5 - speed * 0.4
    for i in range(40):
        tr.update(x + speed * i * DT, i * DT)
    assert abs(tr.v - speed) < 0.05
    assert abs(tr.predict(40 * DT) - (x + speed * 40 * DT)) < 0.01


def test_sudden_turn_is_followed_within_a_few_frames():
    tr = Track1D()
    x = 0.3
    for i in range(30):
        x += 0.5 * DT
        tr.update(x, i * DT)
    errs = []
    for i in range(30, 60):
        x -= 0.5 * DT  # turned around
        tr.update(x, i * DT)
        errs.append(abs(tr.x - x))
    assert max(errs[5:]) < 0.01, "caught up within 5 frames"
    assert tr.v < -0.3


def test_one_wrong_detection_is_ignored_but_a_real_jump_is_accepted():
    t = ReelTracker()
    for i in range(20):
        s = t.update(reel(0.5, (0.4, 0.6)), i * DT)
    s = t.update(reel(0.9, (0.4, 0.6)), 20 * DT)  # a '!' mark or glyph read as the fish
    assert s.usable and abs(s.fish_x - 0.5) < 0.02 and s.rejected == 1
    for i in range(21, 24):
        s = t.update(reel(0.9, (0.4, 0.6)), i * DT)  # it stays there: it is real
    assert abs(s.fish_x - 0.9) < 0.01


def test_short_dropout_is_bridged_long_one_is_reported_lost():
    t = ReelTracker(max_coast=0.3)
    x = 0.4
    for i in range(20):
        x += 0.4 * DT
        t.update(reel(x, (x - 0.1, x + 0.1)), i * DT)
    s = t.update(reel(None, None), 20 * DT + 0.1)   # 100 ms without the fish
    assert s.usable and s.coasting and abs(s.fish_x - (x + 0.4 * 0.1)) < 0.02
    assert s.direction == "right"
    s = t.update(reel(None, None), 20 * DT + 0.5)   # 500 ms: do not guess any more
    assert not s.usable
    s = t.update(reel(x + 0.2, (x + 0.1, x + 0.3)), 20 * DT + 0.55)  # found again: recovers by itself
    assert s.usable and not s.coasting


@pytest.mark.parametrize("width", [0.08, 0.2, 0.45])
def test_bar_width_is_kept_for_any_bar_size(width):
    t = ReelTracker()
    for i in range(10):
        s = t.update(reel(0.5, (0.5 - width / 2, 0.5 + width / 2)), i * DT)
    assert abs((s.bar_right - s.bar_left) - width) < 0.005


def test_noisy_detections_are_smoothed():
    import random
    rnd = random.Random(1)
    tr = Track1D()
    errs = []
    for i in range(200):
        true = 0.5 + 0.3 * math.sin(i * DT * 2)
        tr.update(true + rnd.gauss(0, 0.006), i * DT)
        if i > 20:
            errs.append(abs(tr.x - true))
    assert sum(errs) / len(errs) < 0.006
