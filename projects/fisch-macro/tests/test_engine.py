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
