"""Rod-specific minigames: detectors, solvers (closed loop in the simulator) and presets."""
import pytest

from fischmacro.profiles.rod_presets import apply_preset, find_preset
from fischmacro.profiles.schema import Profile
from fischmacro.simulation.game import SimulatedFischGame
from fischmacro.simulation.harness import run_simulation
from fischmacro.vision import minigames as mg
from fischmacro.vision.frame import Frame


def frame_of(kind, seed=1, t=0.3):
    g = SimulatedFischGame(seed=seed)
    g.rod_minigame = kind
    g._start_reel()
    g.step(t)
    img = g.render()
    return g, Frame(img, (g.width, g.height))


def test_timing_detector_finds_pointer_and_lit_sections():
    p = Profile().minigame
    for t in (0.1, 0.3, 0.55, 0.8):
        g, f = frame_of("lullaby", t=t)
        res = mg.detect_timing(f.crop(Profile().region("mini")), p.pointer_color, p.pointer_tolerance,
                               p.lit_color, p.lit_tolerance)
        assert res.present and abs(res.pointer - g._pointer()) < 0.02
        assert len(res.segments) == len(g._segments)
        for (a, b), (ta, tb) in zip(sorted(res.segments), sorted(g._segments)):
            assert abs(a - ta) < 0.02 and abs(b - tb) < 0.02


def test_match_detector_picks_the_matching_sign():
    p = Profile()
    for seed in range(6):
        g, f = frame_of("stellarwave", seed=seed)
        res = mg.detect_match(f, p.region("mini_target"), p.region("mini"), p.minigame.symbol_color,
                              p.minigame.symbol_tolerance)
        assert res.target_present and len(res.options) == 4
        name = next(n for n, x, y in g._signs if abs(x - res.best.x) < 0.03)
        assert name == g._target_sign


def test_targets_detector():
    p = Profile()
    g, f = frame_of("targets")
    res = mg.detect_targets(f, p.region("mini"), p.minigame.target_color, p.minigame.target_tolerance)
    assert len(res.targets) == len(g._targets)


@pytest.mark.parametrize("kind,action", [("lullaby", "e"), ("stellarwave", "click"), ("targets", "click")])
def test_rod_minigame_solved_while_still_catching(kind, action):
    p = Profile()
    p.minigame.kind, p.minigame.action, p.minigame.lead_ms = kind, action, 0  # the simulator has no input lag
    p.minigame.mode_presses = 1
    g = SimulatedFischGame(seed=3, difficulty=0.4)
    g.rod_minigame, g.mini_action = kind, action
    res = run_simulation(p, game=g, cycles=3, max_time=300, fps=60)
    assert res.outcomes.get("success", 0) == 3, "the bar must keep following the fish"
    assert g.stats.mini_hits >= 3 and g.stats.mini_misses <= g.stats.mini_hits // 5
    if kind == "lullaby":
        assert g.stats.mode_presses == 3  # one Q press per minigame


def test_lullaby_only_mode_leaves_the_bar_alone():
    p = Profile()
    p.minigame.kind, p.minigame.action, p.minigame.lead_ms, p.minigame.keep_reeling = "lullaby", "click", 0, False
    g = SimulatedFischGame(seed=3, difficulty=0.4)
    g.rod_minigame = "lullaby"
    run_simulation(p, game=g, cycles=2, max_time=200, fps=60)
    assert g.stats.mini_hits >= 5 and g.stats.mini_misses == 0


@pytest.mark.parametrize("name,expected", [("Stellarwave Melody Rod", "Stellarwave Melody"), ("LULLABY", "Lullaby"),
                                           ("Pinion's Aria", "Pinion's Aria"), ("Halibut Harpoon", "Halibut Harpoon"),
                                           ("Migurod", "Migurod"), ("Rod of the Depths", None)])
def test_rod_presets(name, expected):
    preset = find_preset(name)
    assert (preset.name if preset else None) == expected
    if preset:
        p = Profile()
        assert apply_preset(p, preset)
