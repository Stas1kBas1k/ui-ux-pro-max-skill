"""Threaded engine tests (real worker threads, simulated capture and input)."""
import time

from fischmacro.automation.engine import AutomationEngine, Status
from fischmacro.input.controller import InputController, RecordingBackend
from fischmacro.profiles.schema import AppSettings, Profile
from fischmacro.vision.capture import CaptureError, CaptureSource
from fischmacro.vision.win32 import WindowInfo


def wait_for(cond, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def sim_settings():
    s = AppSettings()
    s.capture.mode = "simulation"
    s.performance.detection_fps = 40
    return s


def test_never_starts_automation_on_its_own():
    eng = AutomationEngine(sim_settings(), Profile())
    eng.start_vision()
    try:
        time.sleep(0.5)
        assert eng.status == Status.MONITORING
        assert eng.inputs.sent == 0
    finally:
        eng.shutdown()


def test_simulated_session_catches_fish():
    eng = AutomationEngine(sim_settings(), Profile())
    try:
        assert eng.start_automation()
        assert eng.simulated
        assert wait_for(lambda: eng.session.catches >= 1, timeout=40), eng.drain_events()[-15:]
        snap = eng.snapshot()
        assert snap.status == Status.RUNNING and snap.fps > 5
    finally:
        eng.shutdown()
    assert eng.status == Status.STOPPED
    assert eng.inputs.held() == (set(), set())


def test_pause_resume_and_emergency_stop_release_inputs():
    eng = AutomationEngine(sim_settings(), Profile())
    try:
        eng.start_automation()
        assert wait_for(lambda: eng.fsm.state.value == "REELING", timeout=30)
        eng.pause()
        assert eng.status == Status.PAUSED and not eng.inputs.is_held()
        sent = eng.inputs.sent
        time.sleep(0.4)
        assert eng.inputs.sent == sent  # nothing sent while paused
        eng.resume()
        assert eng.status == Status.RUNNING
        assert wait_for(lambda: eng.inputs.is_held(), timeout=15)
        eng.emergency_stop()
        assert not eng.inputs.is_held() and eng.status == Status.MONITORING
        assert not eng.inputs.enabled  # kill switch stays on until next start
        assert eng.start_automation() and eng.inputs.enabled
    finally:
        eng.shutdown()


class MissingWindow(CaptureSource):
    def locate(self):
        return WindowInfo(found=False)

    def grab(self, win, rect=None):
        raise CaptureError("Game window not found")


def test_roblox_closed_stops_automation_with_inputs_released():
    s = AppSettings()
    s.capture.window_lost_timeout = 1.0
    inputs = InputController(RecordingBackend(), click_hold_ms=0)
    eng = AutomationEngine(s, Profile(), source=MissingWindow(), inputs=inputs)
    try:
        eng.start_automation()
        inputs.mouse_down()  # pretend something was held when the game vanished
        assert wait_for(lambda: eng.status == Status.MONITORING, timeout=5)
        assert not inputs.is_held()
        assert "window" in eng.snapshot().last_error.lower()
        assert "not found" in eng.snapshot().message
    finally:
        eng.shutdown()


class Flaky(CaptureSource):
    def locate(self):
        return WindowInfo(True, 0, 0, 800, 600, focused=True)

    def grab(self, win, rect=None):
        raise CaptureError("Capture failed: device lost")


def test_repeated_capture_errors_stop_automation():
    p = Profile()
    p.timing.capture_failure_limit = 3
    eng = AutomationEngine(AppSettings(), p, source=Flaky(), inputs=InputController(RecordingBackend()))
    try:
        eng.start_automation()
        assert wait_for(lambda: eng.status == Status.MONITORING, timeout=5)
        assert "device lost" in eng.snapshot().last_error
    finally:
        eng.shutdown()


def test_focus_loss_pauses_inputs():
    from fischmacro.simulation.game import SimulatedFischGame
    from fischmacro.vision.capture import SimulationCapture

    game = SimulatedFischGame(seed=3)

    class Unfocused(SimulationCapture):
        simulated = False  # behave like a real window that is not focused

        def grab(self, win, rect=None):
            f = super().grab(win, rect)
            f.meta["window_focused"] = False
            return f

    s = AppSettings()
    s.capture.require_focus = True
    inputs = InputController(RecordingBackend(), click_hold_ms=0)
    eng = AutomationEngine(s, Profile(), source=Unfocused(game), inputs=inputs)
    try:
        eng.start_automation()
        time.sleep(0.6)
        assert inputs.sent == 0
        assert "focused" in eng.snapshot().message
    finally:
        eng.shutdown()


def _broken(p):
    """What an older version's live adaptation could leave behind: a reel region moved off screen and a
    sampled colour that matches nothing."""
    from fischmacro.profiles.schema import Region
    p.regions["reel"] = Region(0.85, 0.2, 0.4, 0.05)
    p.detection.bar_color = "#123456"
    return p


def test_start_repairs_a_broken_screen_setup_instead_of_doing_nothing():
    from fischmacro.vision.autocal import screen_setup_differs
    eng = AutomationEngine(sim_settings(), _broken(Profile()))
    try:
        assert eng.start_automation(), eng.start_report  # used to fail at "profile valid": Start did nothing
        assert not screen_setup_differs(eng.profile)
        assert wait_for(lambda: eng.session.catches >= 1, timeout=40)
    finally:
        eng.shutdown()


def test_live_adaptation_never_outlives_the_run():
    from fischmacro.profiles.schema import Region
    eng = AutomationEngine(sim_settings(), Profile())
    try:
        assert eng.start_automation()
        before = (eng.profile.detection.bar_color, eng.profile.regions["reel"])
        eng.profile.detection.bar_color = "#123456"  # as live adaptation would
        eng.profile.regions["reel"] = Region(0.3, 0.5, 0.4, 0.05)
        eng._adapted = True
        eng.stop_automation("test")
        assert (eng.profile.detection.bar_color, eng.profile.regions["reel"]) == before
    finally:
        eng.shutdown()


def test_reel_never_found_twice_switches_to_the_built_in_setup():
    from fischmacro.vision.autocal import screen_setup_differs
    p = Profile()
    p.detection.bar_color = "#123456"
    eng = AutomationEngine(sim_settings(), p)
    try:
        assert eng.start_automation()
        eng.fsm.shake_stuck_streak = 2
        eng._self_heal()
        assert not screen_setup_differs(eng.profile)
        assert any("built-in screen setup" in m for _, _, m in eng.drain_events())
        eng.stop_automation("test")
        assert eng.profile.detection.bar_color == "#123456"  # the saved setup is not overwritten
    finally:
        eng.shutdown()


def test_old_profiles_get_their_screen_setup_repaired():
    from fischmacro.profiles.manager import upgrade
    from fischmacro.profiles.schema import from_dict, to_dict
    from fischmacro.vision.autocal import screen_setup_differs
    raw = to_dict(_broken(Profile()))
    raw["revision"] = 3
    p = upgrade(from_dict(Profile, raw), raw)
    assert not screen_setup_differs(p) and p.revision == 4


def test_roblox_that_will_not_come_forward_gets_one_click_into_it():
    """Windows often refuses to bring a window forward; after the tries the macro clicks into the game once, as the
    player would, instead of waiting forever ("Start does nothing")."""
    from fischmacro.simulation.game import SimulatedFischGame
    from fischmacro.vision.capture import SimulationCapture

    class Unfocused(SimulationCapture):
        simulated = False

        def grab(self, win, rect=None):
            f = super().grab(win, rect)
            f.meta["window_focused"] = False
            return f

    s = AppSettings()
    s.capture.require_focus = True
    backend = RecordingBackend()
    eng = AutomationEngine(s, Profile(), source=Unfocused(SimulatedFischGame(seed=3)),
                           inputs=InputController(backend, click_hold_ms=0))
    try:
        eng.start_automation()
        assert wait_for(lambda: any(e[0] == "down" for e in backend.events), timeout=12)
        time.sleep(1.5)
        assert sum(e[0] == "down" for e in backend.events) == 1  # once, not a stream of clicks
        assert any("clicked into the game" in m for _, _, m in eng.drain_events())
    finally:
        eng.shutdown()


def test_three_minutes_without_a_reel_writes_a_stall_report_and_starts_over(caplog):
    """Player: "after a few catches it just stops catching". The engine notices, logs what it was doing and
    what it saw, and re-equips and casts again."""
    import logging

    import numpy as np

    from fischmacro.automation.fsm import State
    from fischmacro.vision.engine import Observation
    from fischmacro.vision.frame import Frame
    eng = AutomationEngine(sim_settings(), Profile())
    try:
        eng.fsm.start(0.0)
        eng.fsm._go(State.WAITING_FOR_BITE, 0.0, "test", force=True)
        frame = Frame(np.zeros((720, 1280, 3), np.uint8), (1280, 720), timestamp=0.0)
        o = Observation(timestamp=0.0, ok=True, client_size=(1280, 720))
        eng._stall_watch(frame, o, 0.0)
        eng._stall_watch(frame, o, 100.0)
        assert eng.fsm.state == State.WAITING_FOR_BITE
        with caplog.at_level(logging.WARNING):
            eng._stall_watch(frame, o, 181.0)
        assert eng.fsm.state == State.RECOVERY and eng.fsm.ctx.reason == "stall"
        assert any("Stall report" in r.message for r in caplog.records)
        assert any("stall report saved" in m for _, _k, m in eng.drain_events())
    finally:
        eng.shutdown()


def test_every_reel_ends_with_a_report_line(caplog):
    import logging
    eng = AutomationEngine(sim_settings(), Profile())
    try:
        with caplog.at_level(logging.INFO):
            assert eng.start_automation()
            assert wait_for(lambda: eng.session.catches + eng.session.failures >= 1, timeout=40)
            assert wait_for(lambda: any("Reel report" in r.message for r in caplog.records), timeout=10)
        line = next(r.message for r in caplog.records if "Reel report" in r.message)
        assert "fps" in line and "screen-to-decision" in line and "fish seen" in line and "tracked" in line
    finally:
        eng.shutdown()


def test_reel_recorder_writes_frames_and_decisions(tmp_path, monkeypatch):
    import json
    import time as _t

    import numpy as np

    from fischmacro.diagnostics.reel_report import ReelRecorder
    monkeypatch.setenv("FISCHMACRO_HOME", str(tmp_path))
    rec = ReelRecorder()
    rec.begin({"rod": "Stellarwave Melody"})
    for i in range(10):
        rec.add(np.zeros((40, 200, 3), np.uint8), {"t": i * 0.05, "fish": 0.5})
    folder = rec.folder
    rec.end()
    end = _t.monotonic() + 5
    while _t.monotonic() < end and len(list(folder.glob("*.jpg"))) < 10:
        _t.sleep(0.05)
    rows = [json.loads(x) for x in (folder / "frames.jsonl").read_text().splitlines()]
    assert len(list(folder.glob("*.jpg"))) == 10 and len(rows) == 10 and rows[0]["image"] == "00001.jpg"
    assert str(folder).startswith(str(tmp_path))
