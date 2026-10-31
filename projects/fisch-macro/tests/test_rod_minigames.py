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


@pytest.mark.parametrize("kind,action", [("lullaby", "e"), ("targets", "click")])
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


def _stellar_solver():
    from fischmacro.automation.minigame_solvers import MinigameSolver
    from fischmacro.input.controller import InputController, RecordingBackend

    class Fsm:
        input = InputController(RecordingBackend(), click_hold_ms=0)
        last_obs = object()

        def _screen(self, obs, x, y):
            return int(x * 1920), int(y * 1080)

    s = MinigameSolver(Profile().minigame, Fsm())
    s.cfg.kind = "stellarwave"
    return s, Fsm.input.backend


def _zobs(lit, sign, x, score=0.7, margin=0.3):
    from fischmacro.vision.engine import Observation
    from fischmacro.vision.zodiac import ZodiacObs
    o = Observation()
    o.zodiac = ZodiacObs(found=True, lit=lit, next_sign=sign, x=x, y=0.87, score=score, margin=margin)
    return o


def test_stellarwave_picks_in_order_and_checks_each_pick():
    """The real game (player recording): click the next sign, then its star lights up."""
    s, back = _stellar_solver()
    t = 0.0
    s.update(_zobs(0, "Aries", 0.568), t)
    assert ("move", 1090, 939) in back.events and s.stellar_state == "VERIFY"
    t += 0.3
    s.update(_zobs(1, "Taurus", 0.432), t)  # Aries' star lit: next sign
    assert s.hits == 1
    t += 0.3
    s.update(_zobs(1, "Taurus", 0.432), t)
    assert ("move", 829, 939) in back.events


def test_stellarwave_retries_a_pick_that_did_not_count_and_never_clicks_unsure_matches():
    s, back = _stellar_solver()
    clicks = lambda: len([e for e in back.events if e[0] == "down"])  # noqa: E731
    s.update(_zobs(0, "Aries", 0.5, score=0.41, margin=0.02), 0.0)  # two places look alike
    assert clicks() == 0
    t = 0.0
    for _ in range(20):  # the star never lights: retried with gaps, at most 6 taps
        s.update(_zobs(0, "Aries", 0.568), t)
        t += 0.4
    assert 2 <= clicks() <= 6 and s.misses >= 1


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


@pytest.mark.parametrize("rod,kind", [("Stellarwave Melody", "stellarwave"), ("Halibut Harpoon", "halibut"),
                                      ("MiguRod", "migu")])
def test_presets_pick_the_right_solver(rod, kind):
    p = Profile()
    apply_preset(p, find_preset(rod))
    assert p.minigame.kind == kind


# ---------------------------------------------------------------- key prompts read from the screen
def test_key_prompt_parsing_and_allow_list():
    from fischmacro.rods.prompts import parse_key_prompts
    from fischmacro.vision.ocr import TextBox
    boxes = [TextBox("復の反擎！", 0.55, 0.3, 0.3, 0.1, 0.05), TextBox("Lunch'sSeat", 0.8, 0.6, 0.6, 0.1, 0.05),
             TextBox("SHIFT", 0.83, 0.52, 0.62, 0.08, 0.05), TextBox("Q", 0.9, 0.1, 0.1, 0.02, 0.05)]
    found = parse_key_prompts(boxes, allowed={"shift", "space"})
    assert [p.key for p in found] == ["shift"]                      # Q is not on the allow-list
    assert [p.key for p in parse_key_prompts([TextBox("⇧SHIFT", 0.8, 0, 0, 0, 0)])] == ["shift"]
    assert parse_key_prompts([TextBox("Shift happens today", 0.9, 0, 0, 0, 0)]) == []


def test_real_migu_prompt_is_read_as_shift():
    import time

    import cv2
    from pathlib import Path

    from fischmacro.rods.prompts import PromptReader
    from fischmacro.vision.ocr import OcrEngine
    if not OcrEngine.shared().available:
        pytest.skip("OCR engine not installed")
    img = cv2.imread(str(Path(__file__).parent / "fixtures" / "real" / "migu_counter.webp"))
    r = PromptReader(allowed={"shift", "space"})
    r.request(img)
    end = time.monotonic() + 20
    while r.result is None and time.monotonic() < end:
        time.sleep(0.05)
    assert r.result is not None and r.result.key == "shift"


def test_migu_presses_the_key_read_on_screen_and_retries_once_if_not_taken():
    from fischmacro.automation.minigame_solvers import MinigameSolver
    from fischmacro.input.controller import InputController, RecordingBackend
    from fischmacro.rods.prompts import KeyPrompt
    from fischmacro.vision.engine import Observation

    class Fsm:
        input = InputController(RecordingBackend(), key_hold_ms=0)
        last_obs = None

    s = MinigameSolver(Profile().minigame, Fsm())
    s.cfg.kind = "migu"
    s.latency = 0.0
    s.prompts.request = lambda img: None
    s.prompts.reset = lambda: None
    s.prompts.result = KeyPrompt("space", 0.5, 0.6, 0.9, "SPACE")    # the screen asked for Space
    t = 0.0

    def frame(x):
        nonlocal t
        o = Observation()
        o.timing.present, o.timing.pointer, o.timing.segments = True, x, [(0.47, 0.53)]
        s.update(o, t)
        t += 0.02

    for x in (0.30, 0.38, 0.45, 0.50, 0.55):
        frame(x)
    keys = [e[1] for e in Fsm.input.backend.events if e[0] == "key_down"]
    assert keys == ["space"]
    for _ in range(60):  # the bar stays a second after the press: the press was not taken
        frame(0.6)
    for x in (0.45, 0.50):
        frame(x)
    keys = [e[1] for e in Fsm.input.backend.events if e[0] == "key_down"]
    assert keys == ["space", "space"]
    for _ in range(80):
        frame(0.5)  # never more than one retry
    assert len([e for e in Fsm.input.backend.events if e[0] == "key_down"]) == 2
