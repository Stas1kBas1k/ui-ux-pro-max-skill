"""Regression tests for the Start button, Lullaby mode stability and Sovereign recharge."""
import threading
import time

import pytest

from fischmacro.automation.addons import AddonsService, Recharge, RechargeMachine
from fischmacro.automation.engine import AutomationEngine, Status
from fischmacro.automation.lullaby_mode import switch_lullaby_mode, visible_lullaby_mode, MODE_NAMES
from fischmacro.profiles.schema import AddonsConfig, AppSettings, Profile
from tests.test_engine import sim_settings, wait_for


# ---------------------------------------------------------------- Start / Stop lifecycle
def _engine_threads():
    return [t for t in threading.enumerate() if t.name in ("capture", "vision") and t.is_alive()]


def test_repeated_start_stop_never_leaves_duplicate_engines():
    eng = AutomationEngine(sim_settings(), Profile())
    try:
        for i in range(15):
            assert eng.start_automation(), eng.start_report
            assert all(ok for _, ok, _ in eng.start_report), eng.start_report
            assert eng.status == Status.RUNNING
            assert not eng.start_automation(), "a second Start must not start a second engine"
            time.sleep(0.05 if i % 3 else 0.3)
            eng.stop_automation()
            assert eng.status == Status.MONITORING
            assert eng.inputs.held() == (set(), set())
            assert len(_engine_threads()) == 2
        eng.stop_vision()
        assert wait_for(lambda: not _engine_threads(), 3)
        # restart after a full stop works, and fishes
        assert eng.start_automation()
        assert wait_for(lambda: eng.fsm.state.value not in ("IDLE",), 10)
    finally:
        eng.shutdown()
    assert wait_for(lambda: not _engine_threads(), 3)


def test_start_reports_the_failing_stage(monkeypatch):
    p = Profile()
    monkeypatch.setattr(Profile, "validate", lambda self: ["something that cannot be repaired"])
    eng = AutomationEngine(sim_settings(), p)
    try:
        assert not eng.start_automation()
        failed = [n for n, ok, _ in eng.start_report if not ok]
        assert failed == ["profile valid"]
        assert eng.status == Status.STOPPED and not _engine_threads()
    finally:
        eng.shutdown()


def test_start_repairs_broken_reel_and_shake_regions():
    p = Profile()
    p.regions["reel"].w = 0.0
    p.regions["shake"].enabled = False
    eng = AutomationEngine(sim_settings(), p)
    try:
        assert eng.start_automation(), eng.start_report
        assert not p.validate()
    finally:
        eng.shutdown()


def test_old_threads_stop_even_when_a_new_start_follows_at_once():
    eng = AutomationEngine(sim_settings(), Profile())
    try:
        for _ in range(5):
            eng.start_vision()
            eng.stop_vision()
            eng.start_vision()
            assert len(_engine_threads()) <= 4  # the old pair is on its way out, never more
            eng.stop_vision()
        assert wait_for(lambda: not _engine_threads(), 3)
    finally:
        eng.shutdown()


# ---------------------------------------------------------------- Lullaby mode
class FakeRod:
    """The Lullaby rod: Q cycles the modes. ``readable`` False = the name is not on screen."""
    def __init__(self, mode, readable=True, key_works=True):
        self.i = MODE_NAMES.index(mode)
        self.readable, self.key_works, self.presses = readable, key_works, 0

    def read(self):
        return MODE_NAMES[self.i] if self.readable else ""

    def press(self):
        self.presses += 1
        if self.key_works:
            self.i = (self.i + 1) % len(MODE_NAMES)
        return True


def _switch(rod, want):
    return switch_lullaby_mode(want, rod.read, rod.press, lambda s: False)


def test_lullaby_mode_already_set_is_left_alone():
    rod = FakeRod("Fortuitous Harmony")
    r = _switch(rod, "Fortuitous Harmony")
    assert r.ok and rod.presses == 0


def test_lullaby_switches_to_the_wanted_mode_and_stops_there():
    rod = FakeRod("Resistant Composition")
    r = _switch(rod, "Prismatic Sinfonia")
    assert r.ok and rod.read() == "Prismatic Sinfonia" and rod.presses == 4


def test_lullaby_never_presses_blindly():
    rod = FakeRod("Serene Hymn", readable=False)
    r = _switch(rod, "Fortuitous Harmony")
    assert not r.ok and rod.presses == 0 and rod.i == MODE_NAMES.index("Serene Hymn")


def test_lullaby_stops_when_the_key_does_nothing():
    rod = FakeRod("Serene Hymn", key_works=False)
    r = _switch(rod, "Fortuitous Harmony")
    assert not r.ok and rod.presses == 1


def test_visible_mode_ignores_menus_listing_several_modes():
    assert visible_lullaby_mode("Mode: Quickening Symphony") == "Quickening Symphony"
    assert visible_lullaby_mode("Resistant Composition Quickening Symphony") == ""
    assert visible_lullaby_mode("nothing here") == ""


def test_repeated_starts_do_not_change_the_lullaby_mode():
    """Start/Stop ten times with the mode already right: Q must never be pressed."""
    rod = FakeRod("Quickening Symphony")
    for _ in range(10):
        r = _switch(rod, "Quickening Symphony")
        assert r.ok
    assert rod.presses == 0


def test_engine_checks_the_lullaby_mode_once_per_start(monkeypatch):
    p = Profile()
    p.minigame.kind, p.minigame.lullaby_mode = "lullaby", "Fortuitous Harmony"
    eng = AutomationEngine(sim_settings(), p)
    calls = []
    import fischmacro.automation.engine as em
    monkeypatch.setattr(em, "switch_lullaby_mode",
                        lambda want, read, press, wait: calls.append(want) or
                        __import__("fischmacro.automation.lullaby_mode", fromlist=["x"]).SwitchResult(True, 0, want))
    eng._ensure_lullaby_mode()
    eng._ensure_lullaby_mode()
    assert calls == ["Fortuitous Harmony"]
    eng._lullaby_mode_set = ""  # what a new Start does
    eng._ensure_lullaby_mode()
    assert len(calls) == 2


# ---------------------------------------------------------------- Sovereign recharge
class FakeSovereign:
    def __init__(self, power, gain=4, works=True):
        self.power, self.gain, self.works = power, gain, works
        self.t, self.updated, self.relics = 0.0, 0.0, 0

    def use(self):
        self.relics += 1
        if self.works:
            self.power = min(100, self.power + self.gain)
        self.t += 1.0
        self.updated = self.t  # the watcher reads the new value
        return True

    def read(self):
        return self.power, self.updated

    def wait(self, s):
        self.t += s
        return False

    def now(self):
        return self.t


def test_recharge_stops_at_the_target():
    rc, rod = RechargeMachine(), FakeSovereign(88, gain=6)
    assert rc.run(rod.use, rod.read, rod.wait, 99, rod.now)
    assert rc.state == Recharge.COMPLETE and rod.power >= 99 and rod.relics == 2


def test_recharge_is_bounded_per_attempt():
    rc, rod = RechargeMachine(max_relics=4), FakeSovereign(10, gain=1)
    rc.run(rod.use, rod.read, rod.wait, 99, rod.now)
    assert rod.relics == 4


def test_recharge_without_effect_fails_cools_down_and_then_gives_up():
    """The old bug: a bad reading made it use relics after every catch, forever."""
    svc = AddonsService(AddonsConfig(), session_start=0.0)
    svc.cfg.sovereign.enabled = True
    rod = FakeSovereign(50, works=False)
    used = 0
    for catch in range(200):
        now = catch * 20.0  # a catch every 20 s, for over an hour
        svc.world.power, svc.world.power_updated = rod.power, now
        for _, _ in svc.plan(now):
            before = rod.relics
            rod.t = now
            svc.recharge.run(rod.use, lambda: (rod.power, rod.updated), rod.wait, 99, rod.now)
            used += rod.relics - before
    assert svc.recharge.state == Recharge.DISABLED
    assert used == svc.recharge.max_failures  # one relic per failed attempt, then it stopped


def test_recharge_with_no_new_reading_fails_instead_of_looping():
    rc = RechargeMachine(confirm_s=2.0)
    rod = FakeSovereign(50)
    rod.use = lambda: (setattr(rod, "relics", rod.relics + 1), True)[1]  # power readout never refreshes
    rc.run(rod.use, rod.read, rod.wait, 99, rod.now)
    assert rc.state == Recharge.COOLDOWN and rod.relics == 1 and "reading" in rc.last_message


@pytest.mark.parametrize("aborted", [True])
def test_recharge_can_be_cancelled(aborted):
    rc = RechargeMachine()
    rod = FakeSovereign(50)
    rod.use = lambda: True  # nothing changes, so it waits for a reading...
    assert rc.run(rod.use, rod.read, lambda s: aborted, 99, rod.now) is False  # ...and the abort wins
    assert rc.state == Recharge.IDLE


# ---------------------------------------------------------------- casting
def test_a_cast_the_game_ignored_is_pressed_again_instead_of_waiting_for_the_bite_timeout():
    """Casting too soon after a catch (the game still shows the result) used to lose the cast and wait
    45 s for a bite that could not come. Now the missing power bar is noticed and the cast repeated."""
    from fischmacro.simulation.harness import run_simulation
    p = Profile()
    from fischmacro.simulation.game import SimulatedFischGame
    g = SimulatedFischGame(seed=2)
    g.result_seconds = 2.6  # the result screen outlasts the wait after a catch: the first press is ignored
    res = run_simulation(p, game=g, cycles=5, max_time=400, fps=40)
    assert res.outcomes.get("success", 0) == 5
    assert any("Cast did not start" in m for _, m in res.events)
    assert not any("bite timeout" in m or "no bite" in m for _, m in res.events)
    assert res.sim_time < 5 * 15
