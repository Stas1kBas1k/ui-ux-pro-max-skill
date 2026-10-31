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


def test_real_shake_button_is_found():
    """Real 1905x1067 frame: Fisch's SHAKE button is a dark see-through disc with light text."""
    import cv2
    from pathlib import Path

    from fischmacro.vision.detectors import detect_shake
    from fischmacro.vision.frame import Frame
    root = Path(__file__).parent / "fixtures" / "real"
    img = cv2.imread(str(root / "shake_button.webp"))
    if img is None:
        pytest.skip("webp not supported by this OpenCV build")
    p = Profile()
    res = detect_shake(Frame(img, (img.shape[1], img.shape[0])), p.region("shake"), p.detection)
    assert len(res.targets) == 1
    t = res.targets[0]
    assert abs(t.x - 1200 / 1905) < 0.01 and abs(t.y - 243 / 1067) < 0.01
    # and nothing is clicked on a frame without a shake button
    img = cv2.imread(str(root / "plaguereaver_reel.webp"))
    assert detect_shake(Frame(img, (img.shape[1], img.shape[0])), p.region("shake"), p.detection).targets == []


# ---------------------------------------------------------------- real screenshots sent by the player
def _real(name):
    import cv2
    from pathlib import Path
    img = cv2.imread(str(Path(__file__).parent / "fixtures" / "real" / name))
    if img is None:
        pytest.skip("image format not supported by this OpenCV build")
    return img


@pytest.mark.parametrize("name,fish,bar_right", [
    # Stellarwave: the track is full of zodiac glyphs, the catch bar is the bright gradient run
    ("stellarwave_reel_1.webp", 805, 1195), ("stellarwave_reel_2.webp", 915, 1180),
    # Halibut Harpoon: the '!' is an icon above the bar and must not move the fish
    ("halibut_reel.webp", 955, 1105),
])
def test_real_rod_reels_are_tracked(name, fish, bar_right):
    from fischmacro.vision.engine import VisionEngine
    from fischmacro.vision.frame import Frame
    img = _real(name)
    p = Profile()
    e = VisionEngine(p)
    H, W = img.shape[:2]
    x, y, w, h = p.regions["reel"].to_rect(W, H)
    for _ in range(3):
        r = e.process(Frame(img, (W, H)), ("reel",), "REELING").reel
    assert r.ui_present and r.fish_found and r.bar_found
    assert abs(x + r.fish_x * w - fish) < 6
    assert abs(x + r.bar_right * w - bar_right) < 12


def test_real_migu_counterattack_bar():
    from fischmacro.vision.minigames import detect_migu
    img = _real("migu_counter.webp")
    r = detect_migu(img)
    bar_x0, bar_w = 266, 534  # the red bar in this screenshot
    assert r.present
    assert abs(bar_x0 + r.pointer * bar_w - 635) < 6          # the white line
    (a, b), = r.segments                                    # the orange diamond
    assert abs(bar_x0 + (a + b) / 2 * bar_w - 540) < 10
    assert not detect_migu(img[300:]).present                # no red bar: nothing to press


def test_real_sovereign_power_readout():
    from fischmacro.automation.addons import parse_power
    from fischmacro.vision.ocr import OcrEngine
    if not OcrEngine.shared().available:
        pytest.skip("OCR engine not installed")
    text = OcrEngine.shared().text(_real("readouts/sovereign_power.png"))
    assert parse_power(text) == 90, text
