"""Fixes for the live game: scan-code keys, see-through bar, fish-only steering."""
import numpy as np
import pytest

from fischmacro.input.sendinput import key_to_scan
from fischmacro.profiles.schema import DetectionConfig, Profile
from fischmacro.vision.detectors import ReelResult, detect_reel
from tests.helpers import make_fsm, obs


@pytest.mark.parametrize("key,expected", [
    ("1", (0x02, False, False)), ("\\", (0x2B, False, False)), ("#", (0x04, False, True)),
    ("enter", (0x1C, False, False)), ("Return", (0x1C, False, False)), ("E", (0x12, False, True)),
    ("left", (0x4B, True, False)), ("`", (0x29, False, False)), ("f9", (0x43, False, False)),
])
def test_keys_map_to_scan_codes(key, expected):
    assert key_to_scan(key) == expected


def test_unknown_key_is_refused():
    with pytest.raises(ValueError):
        key_to_scan("not-a-key")


def _strip(bar_rgb, fish_x=None, bar=(60, 120)):
    img = np.full((40, 400, 3), (30, 26, 24), np.uint8)  # dark track (BGR)
    r, g, b = bar_rgb
    img[4:36, bar[0]:bar[1]] = (b, g, r)
    if fish_x is not None:
        img[2:38, fish_x - 3:fish_x + 3] = (0x5B, 0x4B, 0x43)  # #434B5B
    return img


def test_see_through_grey_bar_is_detected():
    res = detect_reel(_strip((0x84, 0x85, 0x87), fish_x=90), DetectionConfig())
    assert res.ui_present and res.bar_found and res.fish_found
    assert 0.12 < res.bar_center < 0.25


def test_grey_bar_ignored_when_second_colour_off():
    cfg = DetectionConfig()
    cfg.bar_tolerance2 = 0
    res = detect_reel(_strip((0x84, 0x85, 0x87), fish_x=90), cfg)
    assert not res.bar_found


def test_fish_only_steering_when_bar_unclear():
    fsm, _, inputs, events = make_fsm()
    from tests.test_fsm import _to_reeling
    t = _to_reeling(fsm)
    o = obs()
    o.reel = ReelResult(ui_present=True, fish_found=True, fish_x=0.85, fish_confidence=1.0)
    fsm.update(o, t + 0.05)
    assert inputs.is_held()
    o.reel = ReelResult(ui_present=True, fish_found=True, fish_x=0.1, fish_confidence=1.0)
    fsm.update(o, t + 0.1)
    assert not inputs.is_held()
    assert any("following the fish" in m for k, m, _ in events if k == "warning")


def test_input_method_option_defaults_to_scan_codes():
    from fischmacro.profiles.schema import AppSettings
    assert AppSettings().input.method.startswith("Scan codes")
    assert Profile().detection.bar_color2 == "#848587"


def test_real_plaguereaver_screenshot():
    """Real 1910x1073 frame from a player: skinned reel with a dark fish marker in the middle."""
    import cv2
    from pathlib import Path
    img = cv2.imread(str(Path(__file__).parent / "fixtures" / "real" / "plaguereaver_reel.webp"))
    if img is None:
        pytest.skip("webp not supported by this OpenCV build")
    p = Profile()
    x, y, w, h = p.regions["reel"].to_rect(img.shape[1], img.shape[0])
    r = detect_reel(img[y:y + h, x:x + w], p.detection)
    assert r.ui_present and r.fish_found
    assert abs((x + r.fish_x * w) - 952) < 8
