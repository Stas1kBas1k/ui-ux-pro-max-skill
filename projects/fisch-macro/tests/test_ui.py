"""Offscreen UI tests: the window builds, pages work, themes apply, calibration saves."""
import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QDoubleSpinBox  # noqa: E402

from fischmacro.automation.engine import Status  # noqa: E402
from fischmacro.diagnostics.stats import StatsStore  # noqa: E402
from fischmacro.profiles.manager import ProfileManager, SettingsStore  # noqa: E402
from fischmacro.profiles.schema import Region  # noqa: E402
from fischmacro.ui.theme import THEMES, TEXT_SIZES, apply_theme, stylesheet  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    from fischmacro.app.context import AppContext
    from fischmacro.ui.main_window import MainWindow
    ctx = AppContext(SettingsStore(tmp_path / "settings.json"), ProfileManager(tmp_path / "profiles"),
                     StatsStore(tmp_path / "stats.sqlite3"))
    ctx.use_simulation_for_this_run()
    ctx.settings.risk_acknowledged = True
    win = MainWindow(ctx)
    win.show()
    yield win
    ctx.engine.stop_automation("test end")
    win.close()


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def test_all_pages_render(app, window):
    for i in range(len(window.NAV)):
        window.select_page(i)
        pump(app, 0.1)
        assert window.stack.currentIndex() == i
    assert window.ctx.engine.status == Status.STOPPED  # opening pages never starts anything


@pytest.mark.parametrize("theme", list(THEMES))
def test_every_theme_and_text_size_builds(app, theme):
    for size in TEXT_SIZES:
        apply_theme(theme, size)
        css = stylesheet()
        assert THEMES[theme]["primary"] in css
    apply_theme("Midnight Violet")


def test_config_form_edits_profile(app, window):
    form = window.automation._forms[2]  # reel controller
    spins = form.findChildren(QDoubleSpinBox)
    assert spins
    spins[0].setValue(6.5)  # Kp is the first field
    assert window.ctx.profile.reel.kp == 6.5


def test_start_pause_stop_from_buttons(app, window):
    window.dashboard.start_requested.emit()
    pump(app, 1.0)
    eng = window.ctx.engine
    assert eng.status == Status.RUNNING and eng.simulated
    window.dashboard.pause_requested.emit()
    assert eng.status == Status.PAUSED
    window.dashboard.stop_requested.emit()
    assert eng.status == Status.MONITORING and not eng.inputs.is_held()


def test_calibration_saves_regions_and_colours(app, window):
    window.toggle_calibration()
    cal = window.calibration
    assert cal is not None
    cal._select("reel")
    cal._region_drawn("reel", Region(0.2, 0.8, 0.5, 0.05))
    cal._color_picked("fish_color", "#123456")
    cal._save()
    pump(app, 0.1)
    p = window.ctx.profiles.load(window.ctx.profile.name)
    assert p.regions["reel"] == Region(0.2, 0.8, 0.5, 0.05)
    assert p.detection.fish_color == "#123456"
    assert window.calibration is None


def test_hotkey_page_flags_duplicates(app, window):
    page = window.hotkeys
    page._set("pause", "f6")  # same as start
    assert page.conflicts.isVisibleTo(page)
    assert "F6" in page.conflicts.text()
    page._set("pause", "f7")
    assert not page.conflicts.isVisibleTo(page)


def test_toasts_stack_bottom_right(app, window):
    window.toast("A", "first")
    window.toast("B", "second")
    pump(app, 0.3)
    ts = window.toasts.toasts
    assert len(ts) == 2
    for t in ts:
        assert t.y() > window.stack.height() / 2  # never over the top controls
