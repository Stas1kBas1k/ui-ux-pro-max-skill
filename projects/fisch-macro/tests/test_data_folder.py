"""Data folder: next to the app, never drive C (player: "never put anything on disk c")."""
from __future__ import annotations

import sys

import pytest

from fischmacro import paths


@pytest.fixture
def frozen_app(tmp_path, monkeypatch):
    app = tmp_path / "D" / "MACROS" / "FischMacro"
    app.mkdir(parents=True)
    monkeypatch.delenv("FISCHMACRO_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "FischMacro.exe"))
    monkeypatch.setattr(paths, "_CHOSEN", None)
    monkeypatch.setattr(paths, "NOTE", [])
    # never look at this machine's real drives (the Windows CI runner has a D: and keeps temp files on C:)
    monkeypatch.setattr(paths, "_other_fixed_drives", lambda: [])
    monkeypatch.setattr(paths, "_system_drive", lambda: tmp_path / "Csystem")
    return app


def test_data_is_kept_next_to_the_app(frozen_app):
    assert paths.data_dir() == frozen_app.resolve() / "data"
    assert paths.describe_location().startswith("Data folder: ")


def test_unwritable_app_folder_falls_back_to_the_same_drive(frozen_app, monkeypatch):
    real = paths._writable

    def writable(base):
        if base.name == "data":
            paths.NOTE.append(f"cannot write to {base}: denied")
            return False
        return real(base)
    monkeypatch.setattr(paths, "_writable", writable)
    d = paths.data_dir()
    assert d == frozen_app.resolve().parent / "FischMacro-data"
    assert "cannot write to" in paths.describe_location()


def test_old_data_on_drive_c_is_moved_without_overwriting_newer_files(frozen_app, tmp_path, monkeypatch):
    old = tmp_path / "C" / "AppData" / "Roaming" / "FischMacro"
    (old / "profiles").mkdir(parents=True)
    (old / "profiles" / "Lullaby - Hollowed Harp.json").write_text("old harp")
    (old / "profiles" / "Rod.json").write_text("old rod")
    (old / "settings.json").write_text("old settings")
    new = frozen_app.resolve() / "data"
    (new / "profiles").mkdir(parents=True)
    (new / "profiles" / "Rod.json").write_text("new rod")
    monkeypatch.setenv("APPDATA", str(tmp_path / "C" / "AppData" / "Roaming"))
    monkeypatch.setattr(sys, "platform", "win32")
    d = paths.data_dir()
    assert (d / "profiles" / "Lullaby - Hollowed Harp.json").read_text() == "old harp"
    assert (d / "profiles" / "Rod.json").read_text() == "new rod"
    assert (d / "settings.json").read_text() == "old settings"
    assert not old.exists(), "nothing is left on drive C"
    assert "moved the old data" in paths.describe_location()


def test_app_on_drive_c_with_a_blocked_folder_keeps_data_on_another_drive(frozen_app, tmp_path, monkeypatch):
    """Player's fourth log: the app was in C:\\Users\\...\\Music (Windows blocks writes there, "WinError 2"), so
    data went to C:\\FischMacro-data. Now another fixed drive comes first, and C:\\FischMacro-data is moved there."""
    d_drive = tmp_path / "Ddrive"
    d_drive.mkdir()
    c_root = tmp_path / "Croot"
    (c_root / "FischMacro-data" / "profiles").mkdir(parents=True)
    (c_root / "FischMacro-data" / "profiles" / "Lullaby - Hollowed Harp.json").write_text("harp")
    real = paths._writable

    def writable(base):
        if base.name == "data":
            paths.NOTE.append(f"cannot write to {base}: [WinError 2]")
            return False
        return real(base)
    monkeypatch.setattr(paths, "_writable", writable)
    monkeypatch.setattr(paths, "_same_drive", lambda a, b: True)
    monkeypatch.setattr(paths, "_other_fixed_drives", lambda: [d_drive])
    monkeypatch.setattr(paths, "_system_drive", lambda: c_root)
    monkeypatch.setenv("APPDATA", str(tmp_path / "nothing-here"))
    monkeypatch.setattr(sys, "platform", "win32")
    d = paths.data_dir()
    assert d == d_drive / "FischMacro-data"
    assert (d / "profiles" / "Lullaby - Hollowed Harp.json").read_text() == "harp"
    assert not (c_root / "FischMacro-data").exists()
