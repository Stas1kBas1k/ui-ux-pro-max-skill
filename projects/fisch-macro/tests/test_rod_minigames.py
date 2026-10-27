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
    p.minigame.kind, p.minigame.action = kind, action
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
    p.minigame.kind, p.minigame.action, p.minigame.keep_reeling = "lullaby", "click", False
    g = SimulatedFischGame(seed=3, difficulty=0.4)
    g.rod_minigame = "lullaby"
    g.progress_gain = g.progress_drain = 0.0  # keep the reel going: this measures click accuracy
    run_simulation(p, game=g, cycles=1, max_time=30, fps=60)
    # every click is aimed: the 40 ms input delay of the simulator is learned from the first hits
    assert g.stats.mini_hits >= 10 and g.stats.mini_misses <= g.stats.mini_hits // 5


@pytest.mark.parametrize("latency", [0.02, 0.07, 0.1])
def test_lullaby_learns_the_input_delay(latency):
    p = Profile()
    p.minigame.kind, p.minigame.keep_reeling = "lullaby", False
    g = SimulatedFischGame(seed=5, difficulty=0.4)
    g.rod_minigame, g.input_latency = "lullaby", latency
    g.progress_gain = g.progress_drain = 0.0
    res = run_simulation(p, game=g, cycles=1, max_time=40, fps=60)
    assert g.stats.mini_hits > 2 * g.stats.mini_misses, (g.stats.mini_hits, g.stats.mini_misses)
    assert abs(res.fsm.minigame.latency - latency) < 0.04


@pytest.mark.parametrize("name,expected", [("Stellarwave Melody Rod", "Stellarwave Melody"), ("LULLABY", "Lullaby"),
                                           ("Pinion's Aria", "Pinion's Aria"), ("Halibut Harpoon", "Halibut Harpoon"),
                                           ("Migurod", "Migurod"), ("Rod of the Depths", None)])
def test_rod_presets(name, expected):
    preset = find_preset(name)
    assert (preset.name if preset else None) == expected
    if preset:
        p = Profile()
        assert apply_preset(p, preset)


@pytest.mark.parametrize("seed", range(8))
def test_lullaby_read_on_any_skin_without_colours(seed):
    from fischmacro.simulation.game import random_skin
    g = SimulatedFischGame(seed=seed)
    g.skin = random_skin(seed)
    g.rod_minigame = "lullaby"
    g._start_reel()
    g.step(0.3)
    f = Frame(g.render(), (g.width, g.height))
    res = mg.detect_timing_auto(f.crop(Profile().region("mini")))
    assert res.present and abs(res.pointer - g._pointer()) < 0.02
    truth = []
    for a, b in sorted(g._segments):  # overlapping sections are one section on screen
        if truth and a <= truth[-1][1] + 0.02:
            truth[-1] = (truth[-1][0], max(truth[-1][1], b))
        else:
            truth.append((a, b))
    assert len(res.segments) == len(truth)
    for (a, b), (ta, tb) in zip(sorted(res.segments), truth):
        assert abs(a - ta) < 0.03 and abs(b - tb) < 0.03
