"""Rod Library: per-rod profiles, skins, favourites, recents, drafts, and the page itself."""
import pytest

from fischmacro.profiles.library import DEFAULT_SKIN, RodLibrary, is_dirty
from fischmacro.profiles.manager import ProfileManager
from fischmacro.profiles.schema import LibraryConfig, Profile, Region


@pytest.fixture
def lib(tmp_path):
    pm = ProfileManager(tmp_path / "profiles")
    return RodLibrary(pm, LibraryConfig())


def test_selecting_a_rod_loads_its_recommended_settings_without_saving(lib):
    base = Profile()
    base.regions["reel"] = Region(0.3, 0.8, 0.4, 0.05)  # the user's calibrated screen
    p, created = lib.load_or_create("MiguRod", DEFAULT_SKIN, base)
    assert created and p.minigame.kind == "migu" and p.reel.mode == "precision"
    assert p.regions["reel"].x == 0.3, "screen calibration is carried over"
    assert lib.profiles_for("MiguRod") == [], "nothing is written until Save"
    lib.save(p)
    p2, created = lib.load_or_create("MiguRod", DEFAULT_SKIN, base)
    assert not created and p2.name == "MiguRod"


def test_every_rod_gets_its_own_behaviour(lib):
    kinds = {r: lib.load_or_create(r, DEFAULT_SKIN, Profile())[0].minigame.kind
             for r in ("Lullaby", "MiguRod", "Halibut Harpoon", "Carbon Rod", "Stellarwave Melody")}
    assert kinds == {"Lullaby": "lullaby", "MiguRod": "migu", "Halibut Harpoon": "halibut", "Carbon Rod": "none",
                     "Stellarwave Melody": "stellarwave"}


def test_unknown_rod_falls_back_to_standard_reeling(lib):
    p, _ = lib.load_or_create("Some Rod Added Next Week", DEFAULT_SKIN, Profile())
    assert p.minigame.kind == "none"


def test_skins_get_their_own_profile_built_from_the_rods_tuning(lib):
    p, _ = lib.load_or_create("Lullaby", DEFAULT_SKIN, Profile())
    p.reel.kp = 4.2  # tuned by the user
    p.detection.fish_color = "#123456"
    lib.save(p)
    lib.add_skin("Lullaby", "Toothly Interstellar")
    assert lib.skins_for("Lullaby") == ["Default", "Toothly Interstellar"]
    sk, created = lib.load_or_create("Lullaby", "Toothly Interstellar", Profile())
    assert created and sk.name == "Lullaby - Toothly Interstellar"
    assert sk.reel.kp == 4.2, "keeps the rod's tuning"
    assert sk.detection.fish_color != "#123456", "but not the other skin's colours"
    lib.save(sk)
    assert set(lib.profiles_for("Lullaby")) == {"Lullaby", "Lullaby - Toothly Interstellar"}
    assert lib.find_profile("Lullaby", "Toothly Interstellar") == "Lullaby - Toothly Interstellar"
    assert lib.find_profile("Lullaby", DEFAULT_SKIN) == "Lullaby"


def test_search_categories_favourites_and_recent(lib):
    assert "MiguRod" in lib.search("migu") or "Migurod" in lib.search("migu")
    special = lib.search("", "Special minigame")
    assert {"Lullaby", "Halibut Harpoon"} <= set(special) and "Carbon Rod" not in special
    assert lib.toggle_favourite("Carbon Rod") and lib.search("", "Favourites") == ["Carbon Rod"]
    assert not lib.toggle_favourite("Carbon Rod") and lib.search("", "Favourites") == []
    for r in ("Carbon Rod", "Lullaby", "Carbon Rod"):
        lib.mark_used(r)
    assert lib.search("", "Recent") == ["Carbon Rod", "Lullaby"]


def test_drafts_know_when_they_have_unsaved_changes(lib):
    import copy
    p, _ = lib.load_or_create("Lullaby", DEFAULT_SKIN, Profile())
    assert is_dirty(p, None)
    saved = copy.deepcopy(p)
    assert not is_dirty(p, saved)
    p.reel.kp += 1
    assert is_dirty(p, saved)


# ---------------------------------------------------------------- the page
pytest.importorskip("PySide6")


@pytest.fixture
def window(tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from fischmacro.app.context import AppContext
    from fischmacro.diagnostics.stats import StatsStore
    from fischmacro.profiles.manager import SettingsStore
    from fischmacro.ui.main_window import MainWindow
    ctx = AppContext(SettingsStore(tmp_path / "settings.json"), ProfileManager(tmp_path / "profiles"),
                     StatsStore(tmp_path / "stats.sqlite3"))
    ctx.use_simulation_for_this_run()
    ctx.settings.risk_acknowledged = True
    win = MainWindow(ctx)
    win.show()
    app.processEvents()
    yield win
    ctx.engine.stop_automation("test end")
    win.close()


def test_five_sections_and_every_tab_open(window):
    assert [t for _, t in window.NAV] == ["Dashboard", "Rod Library", "Automation", "Profiles", "Settings"]
    for page in (window.fishing, window.setup_page, window.addons, window.hunts, window.assistant, window.vision,
                 window.diagnostics, window.logs, window.settings, window.hotkeys):
        window.show_widget(page)
        assert window.current_page() is page


def test_library_flow_pick_rod_skin_save_and_use(window):
    page = window.library
    ctx = window.ctx
    window.select_page(1)
    assert len(page.cards) > 100
    page.search.setText("lullaby")
    assert list(page.cards) == ["Lullaby"]
    page.select("Lullaby")
    assert page.draft.minigame.kind == "lullaby" and "not saved" in page.state_lbl.text()
    page.sens.setValue(8)
    assert page.draft.reel.kp > 3.0
    assert page.use()
    assert ctx.profile.name == "Lullaby" and ctx.profile.minigame.kind == "lullaby"
    assert ctx.profiles.exists("Lullaby") and "Lullaby" in ctx.settings.library.recent
    assert not page.use_btn.isEnabled() and "In use" in page.state_lbl.text()
    page._set_mode("precision")
    assert "Unsaved" in page.state_lbl.text() and page.use_btn.isEnabled()
    page.use()
    assert ctx.profiles.load("Lullaby").reel.mode == "precision"
    # switching rods loads the other rod's behaviour
    page.search.setText("")
    page.select("Halibut Harpoon")
    page.use()
    assert ctx.profile.minigame.kind == "halibut"
    page.select("Lullaby")
    assert page.draft.reel.mode == "precision" and not page.dirty


def test_favourite_star_persists(window):
    page = window.library
    page._toggle_fav("Carbon Rod")
    assert "Carbon Rod" in window.ctx.settings.library.favourites
    page.set_category("Favourites")
    assert list(page.cards) == ["Carbon Rod"]


def test_dashboard_cards_show_rod_and_state(window):
    window.library.select("MiguRod" if "MiguRod" in window.library.cards else "Migurod")
    window.library.use()
    window.poll()
    val, sub = window.dashboard.info["rod"]
    assert "igu" in val.text() and "MiguRod" in sub.text()
