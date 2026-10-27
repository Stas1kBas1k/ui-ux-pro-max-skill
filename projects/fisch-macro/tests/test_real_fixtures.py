"""Optional: run detectors against real Fisch screenshots placed in tests/fixtures/real/.

Each image needs a sibling JSON with any of: state ("reel" | "shake" | "idle"), fish_x, bar_left, bar_right,
progress, button [x, y]. A profile.json (exported from the app) in the same folder supplies the calibration.
"""
import json

import cv2
import pytest

from conftest import FIXTURES
from fischmacro.profiles.schema import Profile, from_dict
from fischmacro.vision.engine import VisionEngine
from fischmacro.vision.frame import Frame

REAL = FIXTURES / "real"
CASES = sorted(p for p in REAL.glob("*.png")) if REAL.exists() else []


@pytest.mark.skipif(not CASES, reason="no real screenshots in tests/fixtures/real")
@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_real_screenshot(path):
    data = json.loads((REAL / "profile.json").read_text())
    profile = from_dict(Profile, data.get("profile", data))
    truth = json.loads(path.with_suffix(".json").read_text())
    img = cv2.imread(str(path))
    obs = VisionEngine(profile).process(Frame(img, (img.shape[1], img.shape[0])))
    state = truth.get("state")
    if state == "reel":
        assert obs.reel.present
        for key in ("fish_x", "bar_left", "bar_right"):
            if key in truth:
                assert abs(getattr(obs.reel, key) - truth[key]) < 0.03
        if "progress" in truth:
            assert abs(obs.progress.fill - truth["progress"]) < 0.05
    elif state == "shake":
        assert obs.shake.present
        if "button" in truth:
            bx, by = truth["button"]
            assert any(abs(t.x - bx) < 0.02 and abs(t.y - by) < 0.02 for t in obs.shake.targets)
    elif state == "idle":
        assert not obs.reel.ui_present and not obs.shake.present
