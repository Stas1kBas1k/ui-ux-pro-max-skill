"""Rod mechanics researched on the Fisch wiki and checked in the test game (docs/SPECIAL_RODS.md)."""
import numpy as np

from fischmacro.profiles.schema import Profile
from fischmacro.simulation.game import SimulatedFischGame
from fischmacro.simulation.harness import run_simulation
from fischmacro.vision.falling import Drop, FallingObjects, catch_aim


def _play(kind, game_kind, seeds=3, **game):
    hits = miss = ok = n = 0
    for seed in range(seeds):
        p = Profile()
        p.minigame.kind = kind
        g = SimulatedFischGame(seed=seed, difficulty=0.4)
        g.rod_minigame = game_kind
        for k, v in game.items():
            setattr(g, k, v)
        r = run_simulation(p, game=g, cycles=3, max_time=200, fps=40)
        hits, miss = hits + g.stats.mini_hits, miss + g.stats.mini_misses
        ok, n = ok + r.outcomes.get("success", 0), n + sum(r.outcomes.values())
    return hits, miss, ok, n


def test_inverted_controls_are_noticed_and_flipped():
    """Dreambreaker: 'After 40% progress ... the fishing minigame's input is inverted' (wiki). Without the
    handler the test game caught 0 of 9."""
    ok = n = 0
    for seed in range(3):
        g = SimulatedFischGame(seed=seed, difficulty=0.4)
        g.invert_after = 0.4
        r = run_simulation(Profile(), game=g, cycles=3, max_time=200, fps=40)
        ok, n = ok + r.outcomes.get("success", 0), n + sum(r.outcomes.values())
    assert n == 9 and ok == 9


def test_falling_objects_are_caught_without_losing_the_fish():
    off = _play("none", "falling")
    on = _play("falling", "falling")
    assert on[2] == on[3] == 9  # every fish still caught
    rate = lambda r: r[0] / max(1, r[0] + r[1])  # noqa: E731
    assert rate(on) > rate(off) + 0.15, (off, on)


def test_detector_finds_any_falling_shape_and_ignores_the_still_background():
    f = FallingObjects()
    bg = np.random.default_rng(1).integers(30, 60, (80, 400, 3), dtype=np.uint8)  # a busy still background
    out = []
    for i in range(12):
        img = bg.copy()
        y = 5 + i * 5
        img[y:y + 6, 200:206] = (40, 200, 255)  # an object falling at x = 0.5
        out = f.update(img, i / 30)
    assert out and abs(out[0].x - 0.5) < 0.03 and out[0].vy > 0 and out[0].eta is not None


def test_catch_aim_keeps_the_fish_inside():
    drops = [Drop(0.62, 0.9, vy=1.0, seen=3)]
    aim = catch_aim(0.50, 0.40, 0.60, drops)  # bar 0.2 wide, centred on the fish
    half, margin = 0.10, 0.2 * 0.06
    assert aim - half + margin <= 0.50 <= aim + half - margin  # the fish stays inside, with the margin
    assert aim - half <= 0.62 <= aim + half  # and the object lands on the bar
    assert catch_aim(0.10, 0.0, 0.2, [Drop(0.9, 0.9, vy=1.0, seen=3)]) == 0.10  # out of reach: stay on the fish


def test_special_action_key_is_pressed_only_when_set():
    from tests.helpers import make_fsm, obs
    from fischmacro.automation.fsm import State
    p = Profile()
    p.minigame.kind = "special_key"
    fsm, backend, _, events = make_fsm(p)
    t = 0.0
    fsm.start(t)
    fsm.state = State.REELING
    for i in range(200):
        fsm.update(obs(reel=(0.5, 0.4, 0.6)), t)
        t += 0.025
    assert not any(e == ("key_down", "e") for e in backend.events)  # no key set: nothing pressed
    p.minigame.special_key = "e"
    for i in range(200):
        fsm.update(obs(reel=(0.5, 0.4, 0.6)), t)
        t += 0.025
    presses = [e for e in backend.events if e == ("key_down", "e")]
    assert 1 <= len(presses) <= 3  # every 2.5 s over 5 s
    assert any(k == "special" and "Special Action key" in m for k, m, _ in events)


def test_every_researched_rod_is_in_the_rod_list_and_has_its_own_card():
    from fischmacro.game_data import ALL_RODS
    from fischmacro.profiles.library import basic_rods
    from fischmacro.rods.catalog import CATALOG
    assert len(CATALOG) >= 60 and all(n in ALL_RODS for n in CATALOG)
    assert not set(CATALOG) & set(basic_rods())
    assert {m.support for m in CATALOG.values()} <= {"verified", "handled", "normal", "bonus-manual", "needs-footage"}
    for name in ("Pinion's Aria", "Santa's Miracle Rod", "Starshell Rod"):
        assert CATALOG[name].kind == "falling"
    assert CATALOG["Tranquility Rod"].support == "needs-footage"  # keys and layout not on the wiki


def test_lullaby_skins_include_hollowed_harp_and_each_gets_its_own_setup(tmp_path):
    from fischmacro.profiles.library import RodLibrary
    from fischmacro.profiles.manager import ProfileManager
    from fischmacro.profiles.schema import LibraryConfig
    lib = RodLibrary(ProfileManager(tmp_path), LibraryConfig())
    skins = lib.skins_for("Lullaby")
    assert skins[0] == "Default" and "Hollowed Harp" in skins
    p, created = lib.load_or_create("Lullaby", "Hollowed Harp", Profile())
    assert created and p.minigame.kind == "lullaby" and p.equipment.skin == "Hollowed Harp"
    assert p.name == "Lullaby - Hollowed Harp"


def test_manual_test_mode_reads_the_gauge_whatever_the_profile():
    """Settings -> Diagnostics -> Test a rod mechanic: the Lullaby gauge is read on the recording even with a
    normal-rod profile, and nothing is sent (vision only)."""
    import cv2
    from pathlib import Path
    from fischmacro.vision.engine import VisionEngine
    from fischmacro.vision.frame import Frame
    from fischmacro.diagnostics.replay import mechanic_summary
    cap = cv2.VideoCapture(str(Path(__file__).parent / "fixtures" / "recording1" / "lullaby_42s.mp4"))
    v = VisionEngine(Profile())
    v.test_kind = "lullaby"
    obs = None
    for i in range(30):
        ok, img = cap.read()
        if not ok:
            break
        obs = v.process(Frame(img, (img.shape[1], img.shape[0]), timestamp=i / 30))
    assert obs is not None and obs.timing.present and obs.timing.source == "gauge"
    assert mechanic_summary(obs, "lullaby").startswith("Gauge found")
