import json

import cv2
import pytest

from conftest import FIXTURES
from fischmacro.profiles.schema import Profile
from fischmacro.vision import detectors as d
from fischmacro.vision.engine import VisionEngine
from fischmacro.vision.frame import Frame


def load(name):
    img_path = next(p for p in FIXTURES.glob(f"{name}.*") if p.suffix in (".png", ".jpg"))
    img = cv2.imread(str(img_path))
    truth = json.loads((FIXTURES / f"{name}.json").read_text())
    return Frame(img, (img.shape[1], img.shape[0])), truth


@pytest.mark.parametrize("name", ["reel_1280x720", "reel_1280x720_q70", "reel_1920x1080", "reel_640x360_noise"])
def test_reel_detection_matches_ground_truth(name):
    frame, truth = load(name)
    obs = VisionEngine(Profile()).process(frame)
    assert obs.reel.present
    assert obs.reel.confidence > 0.6
    tol = 0.02
    assert abs(obs.reel.fish_x - truth["fish_x"]) < tol
    assert abs(obs.reel.bar_left - truth["bar_left"]) < tol
    assert abs(obs.reel.bar_right - truth["bar_right"]) < tol
    assert obs.progress.present
    assert abs(obs.progress.fill - truth["progress"]) < 0.03
    assert obs.summary_state() == "Reel minigame"


@pytest.mark.parametrize("name", ["shake_1280x720", "shake_1600x900"])
def test_shake_button_found(name):
    frame, truth = load(name)
    obs = VisionEngine(Profile()).process(frame)
    assert len(obs.shake.targets) == 1, "the bright cloud must be rejected, only the button found"
    t = obs.shake.targets[0]
    bx, by = truth["button"]
    assert abs(t.x - bx) < 0.01 and abs(t.y - by) < 0.01


def test_cast_power_fill():
    frame, truth = load("cast_1280x720")
    obs = VisionEngine(Profile()).process(frame)
    assert obs.cast.present
    assert abs(obs.cast.fill - truth["power"]) < 0.03


def test_disconnect_dialog():
    frame, _ = load("disconnect_1280x720")
    obs = VisionEngine(Profile()).process(frame)
    assert obs.disconnect.detected
    assert obs.summary_state().startswith("Disconnected")


def test_idle_frame_has_no_false_positives():
    frame, _ = load("idle_1280x720")
    obs = VisionEngine(Profile()).process(frame)
    assert not obs.reel.ui_present
    assert not obs.shake.present
    assert not obs.cast.present
    assert not obs.disconnect.detected


def test_wrong_colour_calibration_means_no_detection():
    frame, _ = load("reel_1280x720")
    p = Profile()
    p.detection.fish_color = "#FF00FF"
    p.detection.fish_any_colour = False
    p.detection.fish_tolerance2 = 0
    obs = VisionEngine(p).process(frame)
    # The bar is still seen (so the minigame is known to be active) but without the fish
    # there is no confident fish+bar pair, so the controller will not steer.
    assert obs.reel.ui_present
    assert not obs.reel.fish_found and not obs.reel.present


def test_roi_frame_crop_matches_full_frame():
    frame, truth = load("reel_1280x720")
    p = Profile()
    x, y, w, h = p.region("reel").to_rect(*frame.client_size)
    px, py, pw, ph = p.region("progress").to_rect(*frame.client_size)
    x0, y0 = min(x, px) - 4, min(y, py) - 4
    x1, y1 = max(x + w, px + pw) + 4, max(y + h, py + ph) + 4
    roi = Frame(frame.image[y0:y1, x0:x1].copy(), frame.client_size, (x0, y0), full=False)
    obs = VisionEngine(p).process(roi, ("reel", "progress"))
    assert obs.reel.present and abs(obs.reel.fish_x - truth["fish_x"]) < 0.02


def test_region_outside_roi_is_not_detected():
    frame, _ = load("reel_1280x720")
    roi = Frame(frame.image[:50, :50].copy(), frame.client_size, (0, 0), full=False)
    assert roi.crop(Profile().region("reel")) is None


def test_template_matching(tmp_path):
    frame, truth = load("shake_1280x720")
    bx, by = truth["button"]
    cw, ch = frame.client_size
    cx, cy = int(bx * cw), int(by * ch)
    tpl = frame.image[cy - 20:cy + 20, cx - 30:cx + 30]
    path = tmp_path / "shake.png"
    cv2.imwrite(str(path), cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY))
    p = Profile()
    p.detection.shake_template = str(path)
    p.detection.shake_template_ref_h = ch
    res = d.detect_shake(frame, p.region("shake"), p.detection, d.TemplateCache())
    assert res.present
    assert abs(res.targets[0].x - bx) < 0.01 and abs(res.targets[0].y - by) < 0.01


def test_template_scales_with_resolution(tmp_path):
    frame, truth = load("shake_1280x720")
    bx, by = truth["button"]
    cx, cy = int(bx * 1280), int(by * 720)
    tpl = cv2.cvtColor(frame.image[cy - 20:cy + 20, cx - 30:cx + 30], cv2.COLOR_BGR2GRAY)
    path = tmp_path / "shake.png"
    cv2.imwrite(str(path), tpl)
    big = cv2.resize(frame.image, (1920, 1080), interpolation=cv2.INTER_LINEAR)
    p = Profile()
    p.detection.shake_template, p.detection.shake_template_ref_h = str(path), 720
    res = d.detect_shake(Frame(big, (1920, 1080)), p.region("shake"), p.detection, d.TemplateCache())
    assert res.present and abs(res.targets[0].x - bx) < 0.01


def test_empty_inputs_are_safe():
    cfg = Profile().detection
    assert not d.detect_reel(None, cfg).present
    assert not d.detect_progress(None, cfg).present
    assert not d.detect_cast(None, cfg).present
    assert not d.detect_disconnect(None, cfg).detected


def test_fish_found_by_shape_with_any_colour():
    frame, truth = load("reel_1280x720")
    p = Profile()
    p.detection.fish_color = "#FF00FF"  # wrong on purpose
    obs = VisionEngine(p).process(frame)
    assert obs.reel.fish_found
