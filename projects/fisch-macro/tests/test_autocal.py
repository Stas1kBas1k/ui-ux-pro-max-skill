"""Auto-calibration: find the minigame and its colours without user input."""
import copy
import random
import time

import pytest

from fischmacro.automation.engine import AutomationEngine
from fischmacro.input.controller import InputController
from fischmacro.profiles.schema import DEFAULT_REGIONS, AppSettings, DetectionConfig, Profile, Region
from fischmacro.simulation.game import SimulatedFischGame, SimulatedInputBackend
from fischmacro.vision.autocal import AutoCalibrator, apply_result, calibrate
from fischmacro.vision.capture import SimulationCapture


def random_skin(seed):
    r = random.Random(seed)
    regs = copy.deepcopy(DEFAULT_REGIONS)
    regs["reel"] = Region(r.uniform(0.2, 0.35), r.uniform(0.74, 0.84), r.uniform(0.3, 0.5), r.uniform(0.035, 0.06))
    ro = regs["reel"]
    regs["progress"] = Region(ro.x + ro.w * 0.2, ro.y + ro.h + 0.012, ro.w * 0.6, 0.016)
    c = DetectionConfig()
    c.bar_color = "#%02X%02X%02X" % (r.randint(150, 255), r.randint(150, 255), r.randint(150, 255))
    c.fish_color = "#%02X%02X%02X" % (r.randint(0, 110), r.randint(0, 110), r.randint(0, 110))
    c.progress_color = "#%02X%02X%02X" % (r.randint(60, 255), r.randint(160, 255), r.randint(60, 200))
    return regs, c


def minigame_frames(game, n=32, steer=True):
    game._start_reel()
    frames = []
    for i in range(n):
        game.mouse_held = steer and (i // 4) % 2 == 0
        for _ in range(15):
            game.step(1 / 120)
            game.progress = min(0.9, max(0.1, game.progress))  # keep the minigame on screen
        frames.append(game.render())
    return frames


@pytest.mark.parametrize("steer", [True, False], ids=["moving-bar", "parked-bar"])
def test_finds_reel_and_colours_for_random_skins(steer):
    ok = 0
    seeds = range(12)
    for seed in seeds:
        regs, c = random_skin(seed)
        g = SimulatedFischGame(1280, 720, seed=seed, regions=regs, colors=c)
        res = calibrate(minigame_frames(g, steer=steer))
        t, r = regs["reel"], res.reel
        ok += (r is not None and abs(r.x - t.x) < 0.02 and abs(r.w - t.w) < 0.03 and abs(r.y - t.y) < 0.02
               and res.bar_color == c.bar_color and res.fish_color == c.fish_color)
    assert ok >= 11, f"only {ok}/12 skins calibrated"


def test_nothing_found_without_minigame():
    g = SimulatedFischGame(seed=1)
    frames = []
    for _ in range(20):
        g.step(0.1)
        frames.append(g.render())  # idle scene with moving water only
    res = calibrate(frames)
    assert not res.ok and res.reel is None


def test_validation_rejects_bad_result():
    regs, c = random_skin(3)
    g = SimulatedFischGame(seed=3, regions=regs, colors=c)
    frames = minigame_frames(g)
    cal = AutoCalibrator()
    for i, f in enumerate(frames[-3:]):
        cal.add(f, i * 0.1)
    good = calibrate(frames)
    assert cal.validate(Profile(), good)
    bad = copy.deepcopy(good)
    bad.fish_color = "#FF00FF"
    assert not cal.validate(Profile(), bad)


def test_apply_result_reports_changes():
    regs, c = random_skin(2)
    g = SimulatedFischGame(seed=2, regions=regs, colors=c)
    res = calibrate(minigame_frames(g))
    p = Profile()
    changed = apply_result(p, res)
    assert "reel region" in changed and "bar color" in changed
    assert p.detection.bar_color == c.bar_color


def test_engine_adapts_to_new_skin_and_catches():
    regs = copy.deepcopy(DEFAULT_REGIONS)
    regs["reel"] = Region(0.22, 0.79, 0.50, 0.05)
    regs["progress"] = Region(0.32, 0.855, 0.30, 0.016)
    skin = DetectionConfig()
    skin.bar_color, skin.fish_color, skin.progress_color = "#9EE7FF", "#7A1020", "#7CFF6A"
    game = SimulatedFischGame(seed=5, regions=regs, colors=skin)
    profile = Profile()  # default colours: wrong for this skin
    saved = []
    eng = AutomationEngine(AppSettings(), profile, source=SimulationCapture(game),
                           inputs=InputController(SimulatedInputBackend(game), 0, 0, False))
    eng.on_profile_changed = saved.append
    try:
        eng.start_automation()
        end = time.time() + 60
        while time.time() < end and eng.session.catches < 1:
            time.sleep(0.1)
        assert eng.session.catches >= 1
        assert profile.detection.bar_color == "#9EE7FF" and saved
    finally:
        eng.shutdown()
