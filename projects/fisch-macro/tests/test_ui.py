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
    from fischmacro.ui.pages.automation import AutomationPage
    page = AutomationPage(window.ctx)  # the "Advanced" dialog content
    form = page._forms[2]  # reel controller
    spins = form.findChildren(QDoubleSpinBox)
    kp = next(sp for sp in spins if abs(sp.value() - window.ctx.profile.reel.kp) < 1e-9 and sp.maximum() == 20.0)
    kp.setValue(6.5)
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


def test_addons_page_edits_settings(app, window):
    page = window.addons
    a = window.ctx.settings.addons
    card = page.cards["sovereign"]
    card.check.setChecked(True)
    assert a.sovereign.enabled
    assert not card.body.isVisible()
    card.toggle_expanded()
    assert card.body.isVisibleTo(card)
    window.ctx.engine.addons.on_power_text("Power 77%", 1.0)
    window.select_page(2)
    page.refresh()
    assert page.power_val.text() == "77%"
    stored = window.ctx.settings_store.load()
    assert stored.addons.sovereign.enabled


def test_totem_dropdowns_have_dots_and_save(app, window):
    from fischmacro.ui.components import DotCombo
    card = window.addons.cards["totem"]
    combos = card.findChildren(DotCombo)
    weather = next(c for c in combos if c.findText("Aurora Borealis") >= 0)
    assert not weather.itemIcon(weather.findText("Aurora Borealis")).isNull()
    weather.setCurrentText("Aurora Borealis")
    assert window.ctx.settings.addons.totem.weather == "Aurora Borealis"


def test_hunt_chips_search_and_add(app, window):
    page = window.hunts
    cat = page.catalogue
    cat.chips["Megalodon"].click()
    assert "Megalodon" in window.ctx.settings.hunts.watched
    cat.search.setText("mega")
    assert cat.chips["Megalodon"].isVisibleTo(cat) and not cat.chips["Kraken"].isVisibleTo(cat)
    cat.search.setText("Lucky Pool")
    cat._add_typed()
    h = window.ctx.settings.hunts
    assert "Lucky Pool" in h.custom and "Lucky Pool" in h.watched
    kinds = [w.kind for w in window.ctx.engine.active_watchers()]
    assert "hunt" in kinds
    cat.remove("Lucky Pool")
    assert "Lucky Pool" not in window.ctx.settings.hunts.custom


def test_fishing_page_dropdowns(app, window):
    from fischmacro.ui.components import DotCombo
    page = window.fishing
    combos = page.findChildren(DotCombo)
    cast = next(c for c in combos if c.findText("Normal") >= 0 and c.findText("Perfect") >= 0)
    cast.setCurrentText("Normal")
    assert window.ctx.profile.casting.mode == "normal"
    mini = next(c for c in page.findChildren(DotCombo) if c.findText("Lullaby") >= 0 and c.findText("Targets") >= 0)
    mini.setCurrentText("Lullaby")
    pump(app, 0.05)
    assert window.ctx.profile.minigame.kind == "lullaby"
    modes = next(c for c in page.findChildren(DotCombo) if c.findText("Serene Hymn") >= 0)
    modes.setCurrentText("Serene Hymn")
    assert window.ctx.profile.minigame.lullaby_mode == "Serene Hymn"


def test_rod_preset_applies_from_fishing_page(app, window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    page = window.fishing
    idx = page.rod_combo.findText("Stellarwave Melody")
    page._apply_rod(idx)
    assert window.ctx.profile.minigame.kind == "stellarwave"
