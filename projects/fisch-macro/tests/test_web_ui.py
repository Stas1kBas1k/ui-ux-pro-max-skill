"""The new (HTML) interface: every call the page makes reaches the engine, and the page itself loads and
runs without script errors in the real QtWebEngine."""
import json
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from fischmacro.automation.engine import Status  # noqa: E402
from fischmacro.diagnostics.stats import StatsStore  # noqa: E402
from fischmacro.profiles.manager import ProfileManager, SettingsStore  # noqa: E402
from fischmacro.rods.config import SENSITIVITY  # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "fischmacro" / "web"


class FakeWindow:
    """Stands in for the main window: records what the page asked the desktop for."""

    def __init__(self, export_path=None, import_path=None):
        self.asked = []
        self.export_path, self.import_path = export_path, import_path

    def native_action(self, what, arg=None):
        self.asked.append((what, arg))
        return {"save_file": self.export_path, "open_file": self.import_path}.get(what)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(app, tmp_path):
    from fischmacro.app.context import AppContext
    c = AppContext(SettingsStore(tmp_path / "settings.json"), ProfileManager(tmp_path / "profiles"),
                   StatsStore(tmp_path / "stats.sqlite3"))
    c.use_simulation_for_this_run()
    c.settings.risk_acknowledged = True
    yield c
    c.engine.stop_automation("test end")
    c.shutdown()


@pytest.fixture
def api(ctx, tmp_path):
    from fischmacro.ui.web_api import WebApi
    return WebApi(ctx, FakeWindow(export_path=str(tmp_path / "out.json")))


def test_every_call_in_the_page_exists(api):
    called = set(re.findall(r'api\("([a-z_.]+)"', (WEB / "app.js").read_text()))
    assert len(called) > 25
    assert called <= set(api._methods), called - set(api._methods)


def test_state_is_json_and_complete(api):
    from fischmacro.ui.web_api import json_safe
    s = json.loads(json.dumps(json_safe(api.call("state"))))
    for key in ("status", "running", "game", "rod", "profile", "calibration", "tracking", "session", "hotkeys"):
        assert key in s
    assert s["running"] is False and s["hotkeys"]["start"] == "F6"


def test_choose_rod_and_skin_then_use_it(api, ctx):
    rods = api.call("rods", {"query": "stellar"})
    assert [r["name"] for r in rods["rods"]] == ["Stellarwave Melody"] and rods["total"] >= 150
    d = api.call("rod.open", {"rod": "Stellarwave Melody"})
    assert d["saved"] is False and d["schema"]["behaviour"] == "Stellarwave sign picker"
    d = api.call("draft.set", {"path": SENSITIVITY, "value": 8})
    d = api.call("draft.save", {"use": True})
    assert d["in_use"] and not d["dirty"]
    assert ctx.profile.equipment.rod_name == "Stellarwave Melody"
    assert ctx.profile.minigame.kind == "stellarwave" and ctx.profile.detection.reel_mode == "capsule"
    assert api.call("state")["rod"]["name"] == "Stellarwave Melody"
    # a skin gets its own configuration, starting from the rod's
    d = api.call("rod.add_skin", {"rod": "Stellarwave Melody", "skin": "Cosmic"})
    assert d["skin"] == "Cosmic" and "Cosmic" in d["skins"] and d["saved"] is False
    api.call("draft.save", {"use": True})
    assert ctx.profile.equipment.skin == "Cosmic" and ctx.profile.minigame.kind == "stellarwave"
    # each rod keeps its own configuration
    api.call("rod.open", {"rod": "Stellarwave Melody"})
    assert api.call("draft.set", {"path": SENSITIVITY, "value": 8})["schema"]["rod"] == "Stellarwave Melody"
    names = [p["name"] for p in api.call("profiles")["profiles"]]
    assert len(names) >= 3


def test_basic_rods_share_one_setup(api, ctx):
    r = api.call("rods")
    group = r["rods"][0]
    assert group["group"] and group["name"] == "Basic Rods" and group["count"] > 200
    names = [x["name"] for x in r["rods"]]
    assert r["count"] == r["total"] and "Carbon Rod" not in names
    assert "Lullaby" in names and "Masterline Rod" in names  # special / custom-UI rods keep their own card
    assert [x["name"] for x in api.call("rods", {"query": "carbon"})["rods"]] == ["Carbon Rod"]
    d = api.call("rod.open", {"rod": "Carbon Rod"})
    assert d["rod"] == "Basic Rods" and d["group"]
    api.call("draft.save", {"use": True})
    assert ctx.profile.equipment.rod_name == "Basic Rods"
    assert len(api.call("rods", {"category": "Basic rods"})["rods"]) == group["count"]
    ctx.settings.notifications.auto_profiles = True
    ctx.handle_rod("Carbon Rod")  # a basic rod read off the screen: stays on the shared setup
    assert ctx.profile.equipment.rod_name == "Basic Rods"
    ctx.handle_rod("Lullaby")
    assert ctx.profile.equipment.rod_name == "Lullaby"
    ctx.handle_rod("Carbon Rod")
    assert ctx.profile.equipment.rod_name == "Basic Rods"


def test_profile_editor_save_revert_and_manage(api, ctx):
    d = api.call("profile.open", {"name": ctx.profile.name})
    d = api.call("draft.set", {"path": "casting.mode", "value": "timed"})
    assert d["dirty"]
    assert api.call("draft.revert")["dirty"] is False
    api.call("draft.set", {"path": "casting.mode", "value": "timed"})
    api.call("draft.save", {"use": False})
    assert ctx.profile.casting.mode == "timed"  # the profile in use is updated straight away
    api.call("profile.duplicate", {"name": ctx.profile.name, "new": "Copy"})
    api.call("profile.rename", {"name": "Copy", "new": "Copy 2"})
    assert "Copy 2" in [p["name"] for p in api.call("profiles")["profiles"]]
    from fischmacro.ui.web_api import ApiError
    with pytest.raises(ApiError):
        api.call("profile.delete", {"name": ctx.profile.name})  # the one in use
    api.call("profile.delete", {"name": "Copy 2"})
    assert "Copy 2" not in [p["name"] for p in api.call("profiles")["profiles"]]
    out = api.call("profile.export", {"name": ctx.profile.name})
    assert Path(out["path"]).is_file()


def test_bad_values_are_refused(api):
    from fischmacro.ui.web_api import ApiError
    with pytest.raises(ApiError):
        api.call("draft.set", {"path": "casting.mode", "value": "timed"})  # nothing open yet
    api.call("rod.open", {"rod": "Abaia's Spite"})
    with pytest.raises((ValueError, KeyError)):
        api.call("draft.set", {"path": "casting.mode", "value": "sideways"})
    with pytest.raises(ApiError):
        api.call("nope")
    with pytest.raises(ApiError):
        api.call("settings.set", {"path": "ai.api_key", "value": "x"})  # not a settings-page field


def test_settings_hotkeys_and_licence(api, ctx):
    api.call("settings.set", {"path": "input.observe_only", "value": True})
    assert ctx.settings.input.observe_only is True and api.call("state")["observe_only"] is True
    s = api.call("settings")
    assert all(f["label"] and "_" not in f["label"] for sec in s["sections"] for f in sec["fields"])
    api.call("hotkey.set", {"action": "pause", "key": "f4"})
    assert ctx.settings.hotkeys.pause == "f4"
    lic = api.call("licence")
    assert lic["state"] == "development" and len(lic["device_id"]) >= 12
    assert api.call("about")["version"]


def test_desktop_actions_go_to_the_window(api):
    for name in ("addons", "hunts", "assistant", "vision", "logs"):
        api.call("open_panel", {"name": name})
    api.call("wizard")
    api.call("calibrate.manual")
    asked = api.window.asked
    assert ("panel", "addons") in asked and ("wizard", None) in asked and ("regions", None) in asked


def test_start_stop_and_live_view(api, ctx, app):
    api.call("start")
    deadline = time.time() + 8
    d = {}
    while time.time() < deadline:
        app.processEvents()
        d = api.call("diagnostics", {"image": True})
        if d["image"]:
            break
        time.sleep(0.05)
    assert ctx.engine.status == Status.RUNNING
    assert d["image"] and d["image"].startswith("data:image/jpeg;base64,")
    assert api.call("pause")["paused"] is True
    assert api.call("stop")["running"] is False
    api.call("diagnostics.stop")


def test_bridge_wraps_results_and_errors(api):
    from fischmacro.ui.web_view import Bridge
    b = Bridge(api)
    ok = json.loads(b.handle("about", "{}"))
    assert ok["result"]["name"]
    bad = json.loads(b.handle("profile.delete", json.dumps({"name": api.ctx.profile.name})))
    assert "in use" in bad["error"]
    assert "error" in json.loads(b.handle("rods", "[1, 2]"))


def _web_window(ctx):
    from fischmacro.ui.main_window import MainWindow
    win = MainWindow(ctx, web=True)
    win.resize(1360, 860)
    win.show()
    return win


def _pump_until(app, cond, timeout):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def _js(app, win, code, timeout=5):
    box = {}
    win.web.page().runJavaScript(code, 0, lambda r: box.setdefault("r", r))
    _pump_until(app, lambda: "r" in box, timeout)
    return box.get("r")


def test_the_page_runs_every_section_without_errors(app, ctx):
    try:
        win = _web_window(ctx)
    except ImportError:
        pytest.skip("QtWebEngine is not available")
    try:
        assert _pump_until(app, lambda: win.web.loaded, 30), "page did not load"
        assert _pump_until(app, lambda: _js(app, win, "document.querySelector('#d-title') ? 1 : 0") == 1, 15)
        for page, probe in (("library", ".rod"), ("automation", ".step"), ("profiles", ".pitem"),
                            ("settings", ".field"), ("dashboard", ".tile")):
            _js(app, win, f"go('{page}')")
            assert _pump_until(app, lambda: (_js(app, win, f"document.querySelectorAll('{probe}').length") or 0) > 0,
                               10), page
        # open a rod, then the drawer's controls are live
        _js(app, win, "go('library'); views.library.open('Lullaby')")
        assert _pump_until(app, lambda: _js(app, win, "document.querySelector('#l-use') ? 1 : 0") == 1, 10)
        for tab in ("hotkeys", "diagnostics", "tools", "licence", "about", "general"):
            _js(app, win, f"views.settings.tab='{tab}'; go('settings')")
            _pump_until(app, lambda: False, 0.4)
        # Start from the page: the engine runs and the page shows it
        _js(app, win, "toggleRun()")
        assert _pump_until(app, lambda: ctx.engine.status == Status.RUNNING, 10)
        _js(app, win, "go('dashboard')")
        assert _pump_until(app, lambda: _js(app, win, "document.querySelector('#d-power-label').textContent") == "Stop",
                           10)
        _js(app, win, "toggleRun()")
        assert _pump_until(app, lambda: ctx.engine.status != Status.RUNNING, 10)
        assert not getattr(win.web.page(), "errors", []), win.web.page().errors
    finally:
        ctx.engine.stop_automation("test end")
        win.close()


def test_tool_windows_survive_the_event_loop(app, ctx):
    """Regression: the classic pages behind Add-ons / Hunts / AI assistant / Vision / Logs were deleted
    once the event loop ran (setCentralWidget deletes the old central widget), so every tool button
    failed with RuntimeError in the real app. They now open inside the main window."""
    from PySide6.QtCore import QCoreApplication, QEvent
    try:
        win = _web_window(ctx)
    except ImportError:
        pytest.skip("QtWebEngine is not available")
    try:
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)  # what app.exec() does
        for name in ("addons", "hunts", "assistant", "vision", "logs"):
            win.web.api.call("open_panel", {"name": name})
            # inside the main window (no separate window), over the content area, sidebar left free
            assert win.panel.isVisible() and win.panel.window() is win and win.panel.x() == 248
            assert win.current_page() is getattr(win, name)
        win.web.api.call("panel.close")
        assert not win.panel.isVisible()
        win.on_hotkey("overlay")
        win.on_hotkey("overlay")
        win.poll()
    finally:
        win.close()


def test_special_rods_in_the_library_and_the_mechanic_test(api, ctx):
    rods = {x["name"]: x for x in api.call("rods")["rods"]}
    assert rods["Masterline Rod"]["support"] == "normal" and rods["Masterline Rod"]["custom_ui"]
    assert rods["Tranquility Rod"]["support"] == "needs-footage"
    d = api.call("rod.open", {"rod": "Lullaby"})
    assert "Hollowed Harp" in d["skins"] and d["mechanic"]["support"] == "verified"
    assert "pendulum" in d["mechanic"]["game"]
    d = api.call("rod.open", {"rod": "Pinion's Aria"})
    assert d["schema"]["behaviour"] == "Catch falling objects"
    api.call("diagnostics.mechanic", {"kind": "falling"})
    assert ctx.engine.vision.test_kind == "falling"
    diag = api.call("diagnostics", {"image": False})
    assert diag["mechanic"] == "falling" and any(m["kind"] == "lullaby" for m in diag["mechanics"])
    api.call("diagnostics.stop")
    assert ctx.engine.vision.test_kind is None
    from fischmacro.ui.web_api import ApiError
    with pytest.raises(ApiError):
        api.call("diagnostics.mechanic", {"kind": "nonsense"})


def test_the_interface_writes_nothing_to_disk(app, ctx):
    """The page uses an in-memory browser profile: no cache or storage under %LOCALAPPDATA% (drive C)."""
    try:
        win = _web_window(ctx)
    except ImportError:
        pytest.skip("QtWebEngine is not available")
    try:
        prof = win.web.page().profile()
        assert prof.isOffTheRecord() and not prof.persistentStoragePath().startswith("C:")
        assert _pump_until(app, lambda: win.web.loaded, 30)
    finally:
        win.close()
