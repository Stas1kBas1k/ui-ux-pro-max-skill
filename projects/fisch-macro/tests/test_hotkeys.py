import pytest

from fischmacro.input.hotkeys import HotkeyError, HotkeyManager, find_conflicts, normalize_combo, reserved_conflicts
from fischmacro.profiles.schema import HotkeyConfig


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def manager(bindings=None):
    fired = []
    clock = Clock()
    m = HotkeyManager(bindings or HotkeyConfig().as_dict(), fired.append, clock=clock)
    return m, fired, clock


def test_normalize():
    assert normalize_combo("F6") == "f6"
    assert normalize_combo("Shift + Ctrl + F6") == "ctrl+shift+f6"
    assert normalize_combo("control+a") == "ctrl+a"
    for bad in ["", "ctrl", "ctrl+shift", "f6+f7", "foo"]:
        with pytest.raises(HotkeyError):
            normalize_combo(bad)


def test_default_bindings_fire_actions():
    m, fired, clock = manager()
    for key, action in [("f6", "start"), ("f7", "pause"), ("f8", "stop"), ("f9", "overlay"), ("f10", "calibrate")]:
        m.handle_press(key)
        m.handle_release(key)
        clock.t += 1
    assert fired == ["start", "pause", "stop", "overlay", "calibrate"]


def test_autorepeat_fires_once():
    m, fired, clock = manager()
    for _ in range(10):  # OS key repeat sends many presses without a release
        m.handle_press("f6")
        clock.t += 0.05
    m.handle_release("f6")
    assert fired == ["start"]


def test_debounce_rapid_double_press():
    m, fired, clock = manager()
    m.handle_press("f7"); m.handle_release("f7")
    clock.t += 0.05
    m.handle_press("f7"); m.handle_release("f7")
    assert fired == ["pause"]
    clock.t += 1.0
    m.handle_press("f7"); m.handle_release("f7")
    assert fired == ["pause", "pause"]


def test_modifier_combos():
    m, fired, clock = manager({"start": "ctrl+f6", "stop": "f6"})
    m.handle_press("f6"); m.handle_release("f6")
    clock.t += 1
    m.handle_press("ctrl_l"); m.handle_press("f6"); m.handle_release("f6"); m.handle_release("ctrl_l")
    assert fired == ["stop", "start"]


def test_duplicates_detected_and_skipped():
    bindings = {"start": "f6", "stop": "F6", "pause": "f7"}
    assert find_conflicts(bindings) == {"f6": ["start", "stop"]}
    m, fired, _ = manager()
    errors = m.set_bindings(bindings)
    assert any("already used" in e for e in errors)
    m.handle_press("f6")
    assert fired == ["start"]


def test_invalid_binding_reported():
    m, _, _ = manager()
    errors = m.set_bindings({"start": "ctrl+", "stop": "f8"})
    assert errors and "start" in errors[0]


def test_reserved_conflicts_with_game_keys():
    warnings = reserved_conflicts({"start": "1", "stop": "f8"}, {"rod key": "1"})
    assert warnings and "rod key" in warnings[0]


def test_disabled_manager_does_not_fire():
    m, fired, _ = manager()
    m.enabled = False
    m.handle_press("f8")
    assert fired == []


def test_callback_exception_is_contained():
    def boom(_):
        raise RuntimeError("x")
    m = HotkeyManager({"stop": "f8"}, boom)
    assert m.handle_press("f8") == "stop"
