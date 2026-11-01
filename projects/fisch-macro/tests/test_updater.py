"""In-app updates: release parsing, safe unpacking, the install script (no network: everything is local)."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from fischmacro import updater


def _rel(tag, build_files=True, draft=False):
    assets = []
    if build_files:
        assets = [{"name": "FischMacro-windows.zip", "size": 1234,
                   "browser_download_url": f"https://github.com/x/y/releases/download/{tag}/FischMacro-windows.zip"},
                  {"name": "FischMacro-windows.zip.sha256", "size": 64,
                   "browser_download_url": f"https://github.com/x/y/releases/download/{tag}/FischMacro-windows.zip.sha256"}]
    return {"tag_name": tag, "draft": draft, "body": "Fix tracking\nmore", "assets": assets}


def test_newest_app_release_is_picked():
    r = updater.parse_releases([_rel("fischmacro-b27"), _rel("fischmacro-b30"), _rel("v9"),
                                _rel("fischmacro-b31", build_files=False), _rel("fischmacro-b40", draft=True)])
    assert r.build == 30 and r.tag == "fischmacro-b30" and r.size == 1234 and r.notes.startswith("Fix tracking")
    assert updater.parse_releases({"message": "rate limited"}) is None


def test_only_github_addresses_are_fetched():
    assert updater._allowed("https://api.github.com/repos/a/b/releases")
    assert updater._allowed("https://github.com/a/b/releases/download/t/f.zip")
    assert not updater._allowed("http://github.com/a")
    assert not updater._allowed("https://evil.example/github.com/")


def test_check_reports_a_newer_build(monkeypatch):
    monkeypatch.delenv("FISCHMACRO_NO_NETWORK", raising=False)

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(updater, "_open", lambda url, timeout=0: Resp(json.dumps([_rel("fischmacro-b30")]).encode()))
    u = updater.Updater()
    u.build = 26
    u.check(background=False)
    assert u.state == "available" and u.as_dict()["new_build"] == 30
    u.build = 30
    u.check(background=False)
    assert u.state == "latest"


def test_no_network_means_no_check(monkeypatch):
    monkeypatch.setenv("FISCHMACRO_NO_NETWORK", "1")
    u = updater.Updater()
    u.check()
    assert u.state == "off"


def test_download_is_checked_and_unpacked_into_the_data_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("FISCHMACRO_NO_NETWORK", raising=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("FischMacro.exe", "exe")
        z.writestr("_internal/data/needed.bin", "x")   # a library's own data folder is part of the app
        z.writestr("data/settings.json", "never")       # the app folder's data folder is the player's
    blob = buf.getvalue()
    digest = hashlib.sha256(blob).hexdigest()

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(url, timeout=0):
        return Resp((digest + "  FischMacro-windows.zip\n").encode() if url.endswith(".sha256") else blob)
    monkeypatch.setattr(updater, "_open", fake_open)
    u = updater.Updater()
    u.release = updater.Release(31, "fischmacro-b31", "", "https://github.com/a/b/releases/download/t/z.zip",
                                len(blob), "https://github.com/a/b/releases/download/t/z.zip.sha256")
    u.state = "available"
    u._download()
    staging = u.folder() / "staging"
    assert u.state == "ready" and (staging / "FischMacro.exe").is_file()
    assert (staging / "_internal" / "data" / "needed.bin").is_file()
    assert not (staging / "data").exists()
    assert str(staging).startswith(str(updater.paths.data_dir()))


def test_damaged_download_is_refused(monkeypatch):
    monkeypatch.delenv("FISCHMACRO_NO_NETWORK", raising=False)

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(updater, "_open", lambda url, timeout=0: Resp(b"0" * 64 if url.endswith(".sha256") else b"abc"))
    u = updater.Updater()
    u.release = updater.Release(31, "t", "", "https://github.com/a/z.zip", 3, "https://github.com/a/z.zip.sha256")
    with pytest.raises(ValueError, match="damaged"):
        u._download()


def test_unsafe_zip_entries_are_refused(tmp_path):
    p = tmp_path / "u.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("../../evil.txt", "x")
    with pytest.raises(ValueError, match="unsafe"):
        updater.unpack(p, tmp_path / "out")


def test_install_script_copies_without_deleting_and_restarts(tmp_path):
    s = updater.install_script(4321, tmp_path / "staging", tmp_path / "D's app", tmp_path / "staging",
                               tmp_path / "install.log")
    assert "Wait-Process -Id 4321" in s
    assert "robocopy" in s and "/MIR" not in s and "/PURGE" not in s  # never deletes the player's files
    assert "D''s app" in s  # quotes in paths are escaped for PowerShell
    assert "FischMacro.exe" in s and "Start-Process" in s
