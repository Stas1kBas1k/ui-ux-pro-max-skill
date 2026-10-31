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


def test_match_detector_ranks_the_asked_sign_first_or_second():
    """12 zodiac signs on the bar; similar outlines may tie, which the solver resolves by checking clicks."""
    p = Profile()
    for seed in range(6):
        g, f = frame_of("stellarwave", seed=seed)
        res = mg.detect_match(f, p.region("mini_target"), p.region("mini"), p.minigame.symbol_color,
                              p.minigame.symbol_tolerance)
        assert res.target_present and len(res.options) >= 12
        top2 = sorted(res.options, key=lambda o: o.score, reverse=True)[:2]
        names = [next(n for n, x, y in g._signs if abs(x - o.x) < 0.012) for o in top2]
        assert g._target_sign in names


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
    assert g.stats.mode_presses == 0  # the mode key is never pressed during a catch (it changes the mode)


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
        changed = apply_preset(p, preset)
        assert changed or preset.name == "Stellarwave Melody"  # Stellarwave only reels: defaults already fit


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


# ---------------------------------------------------------------- Stellarwave, MiguRod, Halibut Harpoon
def _rod_game(kind, action="click", seed=3, gain=None):
    g = SimulatedFischGame(seed=seed, difficulty=0.4)
    g.rod_minigame, g.mini_action = kind, action
    if gain is not None:
        g.progress_gain = gain
    return g


def test_stellarwave_clicks_signs_in_order_and_checks_each_click():
    p = Profile()
    p.minigame.kind = "stellarwave"
    g = _rod_game("stellarwave")
    res = run_simulation(p, game=g, cycles=3, max_time=300, fps=60)
    assert res.outcomes.get("success", 0) == 3
    assert g.stats.mini_hits >= 12, "goes through the zodiac order"
    assert g.stats.mini_misses <= g.stats.mini_hits // 4
    assert g.stats.mode_presses == 0


def test_stellarwave_does_not_repeat_a_wrong_sign():
    """Two signs look alike: after a wrong click the other one is tried, never the same one twice."""
    from fischmacro.automation.minigame_solvers import MinigameSolver
    from fischmacro.vision.engine import Observation
    from fischmacro.vision.minigames import MatchOption

    clicks = []

    class Fsm:
        input = None
        last_obs = None

        def _screen(self, obs, x, y):
            return x, y

    s = MinigameSolver(Profile().minigame, Fsm())
    s.cfg.kind = "stellarwave"
    s._act = lambda pos=None: clicks.append(pos)
    obs = Observation()
    obs.match.target_present, obs.match.signature = True, 111
    obs.match.options = [MatchOption(0.40, 0.7, 0.90), MatchOption(0.45, 0.7, 0.89), MatchOption(0.5, 0.7, 0.7),
                          MatchOption(0.55, 0.7, 0.6), MatchOption(0.6, 0.7, 0.1)]
    t = 0.0
    for _ in range(200):  # the target never changes: every click is wrong
        s.update(obs, t)
        t += 0.02
    assert [c[0] for c in clicks] == [0.40, 0.45, 0.5][:len(clicks)] and len(clicks) == 3
    assert s.stellar_state == "GAVE_UP"
    obs.match.signature = 222  # next sign asked: starts again
    s.update(obs, t)
    assert len(clicks) == 4


def test_migu_presses_shift_once_per_timing_bar_in_the_middle():
    p = Profile()
    p.minigame.kind = "migu"
    g = _rod_game("migu", "shift", gain=0.05)
    res = run_simulation(p, game=g, cycles=2, max_time=300, fps=60)
    assert res.outcomes.get("success", 0) == 2
    assert g.stats.mini_hits >= 2 and g.stats.mini_misses == 0, list(res.fsm.minigame.log)


def test_migu_is_separate_from_stellarwave():
    """The Migu solver presses its key, never clicks signs; Stellarwave never presses Shift."""
    p = Profile()
    p.minigame.kind = "migu"
    g = _rod_game("stellarwave", "shift", gain=0.02)  # a Stellarwave screen with the Migu solver
    run_simulation(p, game=g, cycles=1, max_time=120, fps=60)
    assert g.stats.mini_hits == 0
    p.minigame.kind = "stellarwave"
    g = _rod_game("migu", "shift", gain=0.02)
    run_simulation(p, game=g, cycles=1, max_time=120, fps=60)
    assert g.stats.mini_hits == 0 and g.stats.mini_misses <= 1  # only the bar running out


def test_halibut_ignores_marks_and_never_clicks_targets():
    p = Profile()
    p.minigame.kind = "halibut"
    g = _rod_game("halibut")
    res = run_simulation(p, game=g, cycles=3, max_time=300, fps=60)
    assert res.outcomes.get("success", 0) == 3
    assert g.stats.mini_hits >= 1  # harpoons landed while the fish was in the bar
    assert g.stats.mode_presses == 0


def test_halibut_filter_needs_three_frames_to_believe_a_jump():
    from fischmacro.automation.minigame_solvers import MinigameSolver
    from fischmacro.vision.engine import Observation

    s = MinigameSolver(Profile().minigame, None)
    s.cfg.kind = "halibut"
    seen = []
    for i, x in enumerate([0.50, 0.51, 0.85, 0.52, 0.53, 0.80, 0.80, 0.80]):
        o = Observation()
        o.reel.fish_found, o.reel.fish_x = True, x
        s.filter_obs(o, i * 0.03)
        seen.append(round(o.reel.fish_x, 2))
    assert seen == [0.50, 0.51, 0.51, 0.52, 0.53, 0.53, 0.53, 0.80]


@pytest.mark.parametrize("rod,kind", [("Stellarwave Melody", "none"), ("Halibut Harpoon", "halibut"),
                                      ("MiguRod", "migu")])
def test_presets_pick_the_right_solver(rod, kind):
    p = Profile()
    apply_preset(p, find_preset(rod))
    assert p.minigame.kind == kind
