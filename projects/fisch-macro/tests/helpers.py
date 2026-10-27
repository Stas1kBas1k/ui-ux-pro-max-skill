from fischmacro.automation.fsm import FishingStateMachine
from fischmacro.input.controller import InputController, RecordingBackend
from fischmacro.profiles.schema import Profile
from fischmacro.vision import detectors as d
from fischmacro.vision.engine import Observation


def obs(*, reel=None, progress=None, shake=(), cast=None, disconnect=False, popup=False, ok=True,
        focused=True) -> Observation:
    o = Observation(timestamp=0.0, ok=ok, client_size=(1000, 500), screen_origin=(100, 50),
                    window_found=True, window_focused=focused)
    if reel is not None:
        fish, left, right = reel
        o.reel = d.ReelResult(True, fish is not None, fish or 0.0, left, right, 1.0 if fish is not None else 0.0, 1.0)
    if progress is not None:
        o.progress = d.FillResult(True, progress, 1.0)
    o.shake = d.ShakeResult([d.Target(x, y, 0.05, 0.05, 0.95) for x, y in shake])
    if cast is not None:
        o.cast = d.FillResult(True, cast, 1.0)
    if disconnect:
        o.disconnect = d.DialogResult(True, 0.9, "test")
    if popup:
        o.catch_popup = d.DialogResult(True, 0.9, "test")
    return o


def make_fsm(profile=None):
    profile = profile or Profile()
    backend = RecordingBackend()
    inputs = InputController(backend, click_hold_ms=0, key_hold_ms=0, mouse_nudge=False)
    events = []
    fsm = FishingStateMachine(profile, inputs, emit=lambda k, m, **data: events.append((k, m, data)),
                              sleep=lambda s: None)
    return fsm, backend, inputs, events
