import pytest

from fischmacro.automation.fsm import TRANSITIONS, State
from fischmacro.profiles.schema import Profile
from helpers import make_fsm, obs


def drive(fsm, observation, t0, t1, dt=0.025):
    t = t0
    while t <= t1:
        fsm.update(observation, t)
        t += dt
    return t


def test_start_goes_to_casting_and_never_before():
    fsm, backend, _, _ = make_fsm()
    assert fsm.state == State.IDLE
    fsm.update(obs(), 0.0)
    assert backend.events == []  # idle machine sends nothing
    fsm.start(0.0)
    assert fsm.state == State.CASTING


def test_perfect_cast_releases_on_full_power_bar():
    fsm, backend, inputs, events = make_fsm()
    fsm.start(0.0)
    fsm.update(obs(), 0.0)          # phase 0 -> move mouse
    fsm.update(obs(), 0.5)          # pre-cast delay passed -> mouse down
    assert inputs.is_held()
    fsm.update(obs(cast=0.5), 0.8)
    assert inputs.is_held()
    fsm.update(obs(cast=0.97), 1.4)
    assert not inputs.is_held()
    assert fsm.state == State.WAITING_FOR_BITE
    assert fsm.cycle.perfect_cast is True
    assert ("move", 600, 275) in backend.events  # cursor moved to game centre (client -> screen)


def test_cast_releases_after_peak_if_threshold_missed():
    fsm, _, inputs, _ = make_fsm()
    fsm.start(0.0)
    fsm.update(obs(), 0.0)
    fsm.update(obs(), 0.5)
    fsm.update(obs(cast=0.90), 0.6)
    fsm.update(obs(cast=0.86), 0.65)
    assert not inputs.is_held() and fsm.state == State.WAITING_FOR_BITE


def test_timed_fallback_when_power_bar_not_seen():
    p = Profile()
    p.casting.hold_seconds = 0.6
    fsm, _, inputs, events = make_fsm(p)
    fsm.start(0.0)
    fsm.update(obs(), 0.0)
    fsm.update(obs(), 0.4)
    assert inputs.is_held()
    fsm.update(obs(), 0.9)
    assert inputs.is_held()
    fsm.update(obs(), 1.05)
    assert not inputs.is_held()
    assert any(k == "warning" and "not detected" in m for k, m, _ in events)


def _to_waiting(fsm):
    fsm.start(0.0)
    fsm.update(obs(), 0.0)
    fsm.update(obs(), 0.5)
    fsm.update(obs(cast=1.0), 0.6)
    assert fsm.state == State.WAITING_FOR_BITE
    return 1.0


def test_shake_clicks_require_persistence_and_respect_cooldown():
    fsm, backend, _, _ = make_fsm()
    t = _to_waiting(fsm)
    target = obs(shake=[(0.4, 0.4)])
    fsm.update(target, t)
    assert fsm.state == State.SHAKE
    backend.events.clear()
    fsm.update(target, t + 0.03)    # seen once in SHAKE: not yet
    assert not any(e[0] == "down" for e in backend.events)
    fsm.update(target, t + 0.06)    # seen twice -> click
    downs = [e for e in backend.events if e[0] == "down"]
    assert len(downs) == 1
    assert ("move", 500, 250) in backend.events  # 100 + 0.4*1000, 50 + 0.4*500
    fsm.update(target, t + 0.2)     # same spot within cooldown: no second click
    assert len([e for e in backend.events if e[0] == "down"]) == 1
    fsm.update(target, t + 0.7)     # cooldown expired and button still there -> click again
    assert len([e for e in backend.events if e[0] == "down"]) == 2


def test_navigation_shake_mode_uses_keys():
    p = Profile()
    p.shake.mode = "navigation"
    fsm, backend, _, _ = make_fsm(p)
    t = _to_waiting(fsm)
    fsm.update(obs(), t + 1.0)
    assert fsm.state == State.SHAKE
    drive(fsm, obs(), t + 1.0, t + 1.6)
    keys = [e[1] for e in backend.events if e[0] == "key_down"]
    assert keys[0] == "\\" and keys.count("enter") >= 3
    fsm.update(obs(reel=(0.5, 0.4, 0.6)), t + 1.7)
    assert fsm.state == State.REELING
    keys = [e[1] for e in backend.events if e[0] == "key_down"]
    assert keys[-1] == "\\"  # navigation mode toggled off again


def _to_reeling(fsm):
    t = _to_waiting(fsm)
    fsm.update(obs(reel=(0.5, 0.4, 0.6), progress=0.3), t)
    assert fsm.state == State.REELING
    return t


@pytest.mark.parametrize("final,expected", [(0.97, "success"), (0.03, "failure"), (0.5, "unconfirmed")])
def test_reel_outcome_from_progress(final, expected):
    fsm, _, inputs, events = make_fsm()
    t = _to_reeling(fsm)
    t = drive(fsm, obs(reel=(0.7, 0.4, 0.6), progress=final), t, t + 1.0)
    t = drive(fsm, obs(), t, t + 1.0)
    assert fsm.state == State.CATCH_CONFIRMED
    assert not inputs.is_held()
    cycles = [d for k, _, d in events if k == "cycle"]
    assert cycles[-1]["outcome"] == expected


def test_catch_popup_confirms_success():
    p = Profile()
    p.region("progress").enabled = False
    fsm, _, _, events = make_fsm(p)
    t = _to_reeling(fsm)
    t = drive(fsm, obs(reel=(0.5, 0.4, 0.6)), t, t + 0.5)
    t = drive(fsm, obs(popup=True), t, t + 1.0)
    assert [d for k, _, d in events if k == "cycle"][-1]["outcome"] == "success"


def test_reel_holds_and_releases_based_on_tracking():
    fsm, _, inputs, _ = make_fsm()
    t = _to_reeling(fsm)
    drive(fsm, obs(reel=(0.9, 0.3, 0.5)), t, t + 0.3)
    assert inputs.is_held()
    drive(fsm, obs(reel=(0.1, 0.5, 0.7)), t + 0.3, t + 0.6)
    assert not inputs.is_held()


def test_lost_fish_releases_input():
    fsm, _, inputs, events = make_fsm()
    t = _to_reeling(fsm)
    t = drive(fsm, obs(reel=(0.9, 0.3, 0.5)), t, t + 0.3)
    assert inputs.is_held()
    t = drive(fsm, obs(reel=(None, 0.3, 0.5)), t, t + 2.0)  # bar visible, fish not found
    assert not inputs.is_held()
    assert fsm.state == State.REELING
    assert any("Fish indicator lost" in m for _, m, _ in events)


def test_next_cast_after_post_catch_delay():
    fsm, _, _, _ = make_fsm()
    t = _to_reeling(fsm)
    t = drive(fsm, obs(reel=(0.5, 0.4, 0.6), progress=0.99), t, t + 0.2)
    t = drive(fsm, obs(), t, t + 0.8)
    assert fsm.state == State.CATCH_CONFIRMED
    drive(fsm, obs(), t, t + fsm.profile.timing.post_catch_delay + 0.1)
    assert fsm.state == State.CASTING


def test_bite_timeout_recovers_and_recasts():
    p = Profile()
    p.timing.bite_timeout = 5
    p.timing.recovery_delay = 1.0
    fsm, backend, _, events = make_fsm(p)
    t = _to_waiting(fsm)
    t = drive(fsm, obs(), t, t + 5.1)
    assert fsm.state in (State.RECOVERY, State.CASTING)
    assert any(k == "recovery" and "no bite" in m for k, m, _ in events)
    drive(fsm, obs(), t, t + 1.2)
    assert fsm.state == State.CASTING


def test_recovery_resyncs_to_visible_minigame():
    fsm, _, _, _ = make_fsm()
    fsm.resync(0.0)
    assert fsm.state == State.RECOVERY
    fsm.update(obs(reel=(0.5, 0.4, 0.6)), 0.3)
    assert fsm.state == State.REELING


def test_too_many_recoveries_is_an_error():
    p = Profile()
    p.timing.bite_timeout = 3
    p.timing.recovery_delay = 0.1
    p.timing.max_consecutive_recoveries = 2
    fsm, _, inputs, events = make_fsm(p)
    fsm.start(0.0)
    drive(fsm, obs(cast=1.0), 0.0, 40.0, dt=0.05)
    assert fsm.state == State.ERROR
    assert not fsm.running
    assert not inputs.is_held()
    assert any(k == "error" for k, _, _ in events)


def test_disconnect_without_module_stops_with_error():
    fsm, _, inputs, _ = make_fsm()
    t = _to_reeling(fsm)
    drive(fsm, obs(reel=(0.9, 0.3, 0.5)), t, t + 0.2)
    assert inputs.is_held()
    fsm.update(obs(disconnect=True), t + 0.3)
    assert fsm.state == State.ERROR and not inputs.is_held()


def test_disconnect_with_auto_reconnect_clicks_reconnect():
    p = Profile()
    p.modules["auto_reconnect"] = {"enabled": True, "delay": 1.0, "timeout": 60}
    p.region("reconnect_button").enabled = True
    fsm, backend, _, _ = make_fsm(p)
    t = _to_waiting(fsm)
    fsm.update(obs(disconnect=True), t)
    assert fsm.state == State.RECOVERY and fsm.ctx.reason == "disconnect"
    t = drive(fsm, obs(disconnect=True), t, t + 1.2)
    cx, cy = p.region("reconnect_button").center()
    assert ("move", int(100 + cx * 1000), int(50 + cy * 500)) in backend.events
    t = drive(fsm, obs(), t, t + 7.0)
    assert fsm.state == State.CASTING


def test_unknown_frame_never_sends_input():
    fsm, backend, inputs, _ = make_fsm()
    t = _to_reeling(fsm)
    drive(fsm, obs(reel=(0.9, 0.3, 0.5)), t, t + 0.2)
    assert inputs.is_held()
    n = len(backend.events)
    fsm.update(obs(ok=False), t + 0.3)
    assert not inputs.is_held()
    assert all(e[0] == "up" for e in backend.events[n:])


def test_stop_releases_everything():
    fsm, _, inputs, _ = make_fsm()
    t = _to_reeling(fsm)
    drive(fsm, obs(reel=(0.9, 0.3, 0.5)), t, t + 0.2)
    inputs.key_down("w")
    fsm.stop(t + 0.3)
    assert inputs.held() == (set(), set())
    assert fsm.state == State.IDLE and not fsm.running


def test_illegal_transition_rejected():
    fsm, _, _, _ = make_fsm()
    with pytest.raises(RuntimeError):
        fsm._go(State.REELING, 0.0)  # IDLE -> REELING is not allowed
    assert State.CASTING in TRANSITIONS[State.IDLE]


def test_all_states_have_handlers():
    fsm, _, _, _ = make_fsm()
    for s in State:
        if s not in (State.IDLE, State.ERROR):
            assert hasattr(fsm, f"_on_{s.value.lower()}")
