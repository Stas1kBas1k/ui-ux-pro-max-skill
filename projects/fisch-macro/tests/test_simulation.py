"""Closed-loop end-to-end tests: simulated game -> vision -> FSM -> input -> game."""
import pytest

from fischmacro.automation.fsm import State
from fischmacro.profiles.schema import Profile
from fischmacro.simulation.game import SimulatedFischGame
from fischmacro.simulation.harness import run_simulation


@pytest.mark.parametrize("seed,difficulty", [(1, 0.2), (2, 0.5), (3, 0.8)])
def test_full_fishing_cycles(seed, difficulty):
    res = run_simulation(seed=seed, difficulty=difficulty, cycles=5, max_time=400)
    assert len(res.cycles) == 5, res.events[-10:]
    assert res.outcomes.get("success", 0) >= 4
    assert res.game.stats.misclicks == 0
    states = {e[1].split(" -> ")[1].split(" ")[0] for e in res.events if e[0] == "state"}
    assert {"CASTING", "WAITING_FOR_BITE", "SHAKE", "REELING", "CATCH_CONFIRMED"} <= states


def test_high_resolution_and_noise():
    game = SimulatedFischGame(1920, 1080, seed=7, difficulty=0.5, noise=4.0)
    res = run_simulation(game=game, cycles=3, max_time=300)
    assert res.outcomes.get("success", 0) >= 3


def test_low_fps_still_works():
    res = run_simulation(seed=4, difficulty=0.3, cycles=3, fps=20, max_time=300)
    assert res.outcomes.get("success", 0) >= 2


def test_navigation_mode_end_to_end():
    p = Profile()
    p.shake.mode = "navigation"
    res = run_simulation(p, seed=5, difficulty=0.3, cycles=3, max_time=300)
    assert res.outcomes.get("success", 0) >= 3


def test_controller_is_needed():
    """Sanity check of the test itself: a controller that never holds should fail catches."""
    p = Profile()
    p.reel.kp = p.reel.kd = p.reel.feedforward = 0.0
    p.reel.hold_bias = 0.0
    p.modules["session_limits"] = {"enabled": False}
    res = run_simulation(p, seed=6, difficulty=0.5, cycles=3, max_time=300)
    assert res.outcomes.get("failure", 0) >= 2


def test_disconnect_mid_session_stops_safely():
    def on_step(game, fsm, obs):
        if fsm.state == State.REELING and game.t > 0 and not game.state == "disconnected":
            game.disconnect()
    res = run_simulation(seed=8, cycles=5, max_time=120, on_step=on_step)
    assert res.fsm.state in (State.ERROR, State.IDLE)
    assert not res.fsm.input.is_held()
    assert any(k == "disconnect" for k, _ in res.events)


def test_auto_reconnect_end_to_end():
    p = Profile()
    p.modules["auto_reconnect"] = {"enabled": True, "delay": 1.0, "timeout": 60}
    p.region("reconnect_button").enabled = True
    done = {"x": False}

    def on_step(game, fsm, obs):
        if not done["x"] and game.stats.catches == 1 and game.state == "idle":
            done["x"] = True
            game.disconnect()
    res = run_simulation(p, seed=9, cycles=3, max_time=400, on_step=on_step)
    assert done["x"]
    assert res.outcomes.get("success", 0) >= 3
    assert any("Reconnect" in m for _, m in res.events)


def test_auto_hover_learns_asymmetric_rod():
    """A rod whose bar rises fast and falls slowly (true hover duty 0.25) is learned while reeling."""
    p = Profile()
    game = SimulatedFischGame(seed=2, difficulty=0.5)
    game.accel_hold, game.accel_release = 3.6, 1.2
    res = run_simulation(p, game=game, cycles=3, max_time=400)
    learned = res.fsm.reel.hover.value
    assert learned is not None and abs(learned - 0.25) < 0.06
    assert res.outcomes.get("success", 0) >= 2
