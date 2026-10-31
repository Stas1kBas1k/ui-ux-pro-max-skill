"""Per-rod configuration (definitions + editor schema) and the licensing seam."""
import pytest

from fischmacro import licensing
from fischmacro.profiles.rod_presets import apply_preset, find_preset
from fischmacro.profiles.schema import Profile
from fischmacro.rods.config import SENSITIVITY, definition, editor_schema, get_value, set_value


def rod_profile(name):
    p = Profile()
    p.equipment.rod_name = name
    pre = find_preset(name)
    if pre:
        apply_preset(p, pre)
    return p


@pytest.mark.parametrize("rod,behaviour,layout,special", [
    ("Carbon Rod", "none", "standard", False), ("Stellarwave Melody", "stellarwave", "capsule", True),
    ("Lullaby", "lullaby", "standard", True), ("MiguRod", "migu", "standard", True),
    ("Some Rod From Next Update", "none", "standard", False)])
def test_every_rod_has_a_definition(rod, behaviour, layout, special):
    d = definition(rod)
    assert (d.behaviour, d.reel_layout, d.special) == (behaviour, layout, special)


def test_editor_shows_only_what_the_rod_uses():
    normal = editor_schema(rod_profile("Carbon Rod"))
    titles = [s["title"] for s in normal["sections"]]
    assert titles[0] == "Fish tracking" and not any("minigame" in t for t in titles)
    lull = editor_schema(rod_profile("Lullaby"))
    first = lull["sections"][0]
    assert "Lullaby" in first["title"] and any(f["path"] == "minigame.lullaby_mode" and f["simple"]
                                               for f in first["fields"])
    simple = [f["path"] for s in normal["sections"] for f in s["fields"] if f["simple"]]
    assert SENSITIVITY in simple and "reel.mode" in simple and "reel.smoothing" not in simple


def test_values_are_converted_and_kept_in_limits():
    p = rod_profile("Carbon Rod")
    assert set_value(p, "reel.mode", "precision") == "precision"
    with pytest.raises(ValueError):
        set_value(p, "reel.mode", "turbo")
    assert set_value(p, "timing.bite_timeout", "9999") == 600.0  # clamped to its maximum
    assert set_value(p, "shake.persistence_frames", "3.4") == 3
    assert set_value(p, SENSITIVITY, 8) == 8 and p.reel.kp > 3.0
    assert get_value(p, SENSITIVITY) == 8
    with pytest.raises(KeyError):
        set_value(p, "reel.not_a_setting", 1)


def test_licence_is_asked_in_one_place_and_dev_build_allows_everything():
    s = licensing.current()
    assert s.state == "development" and s.allows("automation") and len(s.device_id) == 32
    assert licensing.device_id() == licensing.device_id()


def test_start_refuses_without_a_licence(monkeypatch):
    from fischmacro.automation.engine import AutomationEngine
    from fischmacro.profiles.schema import AppSettings

    class NoLicence(licensing.DevelopmentLicense):
        def status(self):
            s = super().status()
            s.state, s.message = "unlicensed", "No licence"
            return s
    licensing.set_provider(NoLicence())
    try:
        st = AppSettings()
        st.capture.mode = "simulation"
        eng = AutomationEngine(st, Profile())
        assert not eng.start_automation()
        assert eng.start_report[-1][0] == "licence"
    finally:
        licensing.set_provider(licensing.DevelopmentLicense())
