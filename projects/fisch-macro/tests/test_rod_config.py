"""Per-rod configuration (definitions + editor schema) and the licensing seam."""
import pytest

from fischmacro import licensing
from fischmacro.profiles.rod_presets import apply_preset, find_preset
from fischmacro.profiles.schema import Profile
from fischmacro.rods.config import (SENSITIVITY, definition, editor_schema, get_value, sensitivity, set_sensitivity,
                                    set_value)


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
    basic = [f["path"] for f in normal["basic"]]
    assert basic == [SENSITIVITY, "casting.mode", "timing.post_catch_delay", "equipment.rod_slot_key"]
    every = [f["path"] for s in normal["sections"] for f in s["fields"]]
    assert "reel.smoothing" in every and not set(basic) & set(every)  # each setting appears once
    lull = editor_schema(rod_profile("Lullaby"))
    assert [f["path"] for f in lull["basic"]][:2] == ["minigame.lead_ms", "minigame.keep_reeling"]
    assert "Lullaby" in lull["sections"][0]["title"]
    assert all(f["label"] and f["help"] for f in normal["basic"])


def test_sensitivity_is_calm_by_default_and_upgrades_old_profiles():
    from fischmacro.profiles.manager import upgrade
    from fischmacro.profiles.schema import Profile, from_dict, to_dict
    fresh = Profile()
    assert sensitivity(fresh) == 5 and fresh.reel.min_switch_ms == 50
    set_sensitivity(fresh, 10)
    assert fresh.reel.kp == 3.0 and fresh.reel.min_switch_ms == 0  # 10 = the old default
    old = to_dict(Profile())
    old.pop("revision")
    old["reel"].update(kp=3.0, kd=0.45, feedforward=0.25, end_grace=0.6)
    old["timing"]["post_catch_delay"], old["casting"]["pre_cast_delay"] = 1.6, 0.35
    p = upgrade(from_dict(Profile, old), old)
    assert sensitivity(p) == 5 and p.reel.kp == 2.1 and p.reel.min_switch_ms == 50
    assert (p.timing.post_catch_delay, p.casting.pre_cast_delay, p.reel.end_grace) == (0.5, 0.15, 0.35)
    old["timing"]["post_catch_delay"] = 3.0  # set by hand: kept
    assert upgrade(from_dict(Profile, old), old).timing.post_catch_delay == 3.0


def test_values_are_converted_and_kept_in_limits():
    p = rod_profile("Carbon Rod")
    assert set_value(p, "reel.mode", "precision") == "precision"
    with pytest.raises(ValueError):
        set_value(p, "reel.mode", "turbo")
    assert set_value(p, "timing.bite_timeout", "9999") == 600.0  # clamped to its maximum
    assert set_value(p, "shake.persistence_frames", "3.4") == 3
    assert set_value(p, SENSITIVITY, 8) == 8 and p.reel.kp > 2.1 and p.reel.min_switch_ms == 20
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
