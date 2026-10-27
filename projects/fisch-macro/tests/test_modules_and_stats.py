from fischmacro.automation.fsm import State
from fischmacro.automation.modules import REGISTRY
from fischmacro.diagnostics.stats import SessionStats, StatsStore
from fischmacro.profiles.schema import Profile
from helpers import make_fsm, obs


def test_builtin_modules_registered():
    assert {"session_limits", "timed_actions", "totem", "auto_reconnect"} <= set(REGISTRY)
    assert REGISTRY["auto_reconnect"].experimental


def _cycle(fsm, t, progress):
    for _ in range(5):
        fsm.update(obs(reel=(0.5, 0.4, 0.6), progress=progress), t)
        t += 0.05
    for _ in range(30):
        fsm.update(obs(), t)
        t += 0.05
    return t


def test_session_limit_stops_after_n_catches():
    p = Profile()
    p.modules["session_limits"] = {"enabled": True, "max_catches": 1}
    fsm, _, _, events = make_fsm(p)
    fsm.start(0.0)
    fsm._go(State.WAITING_FOR_BITE, 0.0, force=True)
    t = _cycle(fsm, 0.1, 0.99)
    for _ in range(60):
        fsm.update(obs(), t)
        t += 0.05
    assert not fsm.running and fsm.state == State.IDLE
    assert any("Session limit" in m for _, m, _ in events)


def test_timed_action_runs_only_at_safe_point():
    p = Profile()
    p.modules["timed_actions"] = {"enabled": True, "action1_key": "3", "action1_minutes": 0.001,
                                  "action1_click": False, "reequip_rod": True}
    fsm, backend, _, _ = make_fsm(p)
    fsm.start(0.0)
    fsm._go(State.WAITING_FOR_BITE, 0.0, force=True)
    fsm.update(obs(reel=(0.5, 0.4, 0.6), progress=0.5), 1.0)
    assert fsm.state == State.REELING
    for i in range(10):  # due, but must not fire during the minigame
        fsm.update(obs(reel=(0.5, 0.4, 0.6), progress=0.99), 1.0 + i * 0.05)
    assert ("key_down", "3") not in backend.events
    t = 1.6
    while fsm.state != State.CASTING and t < 10:
        fsm.update(obs(), t)
        t += 0.05
    keys = [e[1] for e in backend.events if e[0] == "key_down"]
    assert keys[:2] == ["3", "1"]  # action key, then rod re-equip


def test_broken_module_does_not_break_loop(monkeypatch):
    p = Profile()
    p.modules["totem"] = {"enabled": True}
    fsm, _, _, _ = make_fsm(p)
    fsm.start(0.0)
    monkeypatch.setattr(fsm.modules.modules["totem"], "on_tick", lambda ctx: 1 / 0)
    fsm.update(obs(), 0.1)  # must not raise
    assert fsm.running


def test_stats_store(tmp_path):
    store = StatsStore(tmp_path / "s.sqlite3")
    sid = store.start_session("Default", simulated=True)
    store.add_cycle(sid, "success", 10.0, 0.98, True, 3)
    store.add_cycle(sid, "failure", 20.0, 0.01, False, 4)
    store.add_event(sid, "recovery", "no bite")
    s = SessionStats(session_id=sid, catches=1, failures=1, durations=[10, 20])
    store.end_session(s, "test")
    tot = store.totals()
    assert tot["cycles"] == 2 and tot["success"] == 1 and tot["failure"] == 1
    assert abs(tot["avg_duration"] - 15.0) < 1e-6 and tot["recoveries"] == 1
    rows = store.sessions()
    assert rows[0]["catches"] == 1 and rows[0]["end_reason"] == "test"
    out = tmp_path / "cycles.csv"
    store.export_csv(out)
    assert out.read_text().count("\n") == 3
