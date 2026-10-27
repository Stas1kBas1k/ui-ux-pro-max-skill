
import pytest

from fischmacro.profiles.manager import ProfileError, ProfileManager, SettingsStore
from fischmacro.profiles.schema import AppSettings, Profile, Region, from_dict, to_dict


def test_default_profile_created(home):
    pm = ProfileManager(home / "profiles")
    assert pm.names() == ["Default"]


def test_roundtrip_preserves_values(home):
    pm = ProfileManager(home / "profiles")
    p = pm.create("Rod A")
    p.reel.kp = 7.25
    p.detection.fish_color = "#123456"
    p.regions["reel"] = Region(0.1, 0.2, 0.3, 0.04)
    p.modules["session_limits"] = {"enabled": True, "max_catches": 42}
    pm.save(p)
    q = ProfileManager(home / "profiles").load("Rod A")  # fresh manager = new launch
    assert q.reel.kp == 7.25
    assert q.detection.fish_color == "#123456"
    assert q.regions["reel"] == Region(0.1, 0.2, 0.3, 0.04)
    assert q.modules["session_limits"]["max_catches"] == 42
    # untouched regions keep their defaults
    assert "shake" in q.regions


def test_duplicate_rename_delete(home):
    pm = ProfileManager(home / "profiles")
    p = pm.load("Default")
    p.casting.hold_seconds = 1.7
    pm.save(p)
    dup = pm.duplicate("Default", "Copy")
    assert dup.casting.hold_seconds == 1.7
    pm.rename("Copy", "Renamed")
    assert "Renamed" in pm.names() and "Copy" not in pm.names()
    pm.delete("Renamed")
    assert pm.names() == ["Default"]
    with pytest.raises(ProfileError):
        pm.delete("Default")  # last profile must remain


def test_name_validation(home):
    pm = ProfileManager(home / "profiles")
    for bad in ["", "   ", "../evil", "a/b", "x" * 61]:
        with pytest.raises(ProfileError):
            pm.create(bad)
    with pytest.raises(ProfileError):
        pm.create("Default")


def test_import_export(home, tmp_path):
    pm = ProfileManager(home / "profiles")
    p = pm.load("Default")
    p.shake.mode = "navigation"
    pm.save(p)
    out = tmp_path / "exported.json"
    pm.export("Default", out)
    imported = pm.import_file(out)
    assert imported.name == "Default (2)"
    assert pm.load("Default (2)").shake.mode == "navigation"


def test_import_rejects_garbage(home, tmp_path):
    pm = ProfileManager(home / "profiles")
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    with pytest.raises(ProfileError):
        pm.import_file(bad)


def test_tolerant_loading():
    data = to_dict(Profile())
    data["unknown_key"] = 1
    data["reel"]["kp"] = "not a number"
    del data["casting"]
    p = from_dict(Profile, data)
    assert p.reel.kp == Profile().reel.kp
    assert p.casting.mode == "perfect"


def test_settings_persist_and_recover_from_corruption(home):
    store = SettingsStore(home / "settings.json")
    s = AppSettings()
    s.hotkeys.start = "ctrl+f6"
    s.active_profile = "Rod A"
    store.save(s)
    assert SettingsStore(home / "settings.json").load().hotkeys.start == "ctrl+f6"
    (home / "settings.json").write_text("{broken")
    assert store.load().hotkeys.start == "f6"
    assert (home / "settings.corrupt.json").exists()


def test_region_to_rect_clamps():
    r = Region(0.95, 0.95, 0.2, 0.2)
    x, y, w, h = r.to_rect(100, 100)
    assert x + w <= 100 and y + h <= 100 and w >= 1 and h >= 1
