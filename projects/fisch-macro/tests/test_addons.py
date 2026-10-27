"""Add-ons: readout parsing and what each add-on decides to do."""
import pytest

from fischmacro.automation.addons import AddonsService, parse_power, parse_world
from fischmacro.profiles.schema import AddonsConfig, AppSettings, Profile


@pytest.mark.parametrize("text,expected", [("Power 87%", 87), ("SOVEREIGN 100 %", 100), ("45/100", 45),
                                            ("charge: 9", 9), ("no digits", None), ("250%", None)])
def test_parse_power(text, expected):
    assert parse_power(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Weather: Rain  Night", ("Rain", "Night", "")),
    ("Raging Squall | Day", ("Raging Squall", "Day", "")),
    ("Clear 14:30 Shiny Surge active", ("Clear", "Day", "Shiny")),
    ("Foggy 2:15 am", ("Foggy", "Night", "")),
    ("Aurora Borealis night of the luminous", ("Aurora Borealis", "Night", "Sparkling")),
])
def test_parse_world(text, expected):
    assert parse_world(text) == expected


def _svc(**kw):
    cfg = AddonsConfig()
    for k, v in kw.items():
        setattr(cfg, k, v)
    return AddonsService(cfg, session_start=0.0)


def test_sovereign_recharges_only_below_threshold():
    s = _svc()
    s.cfg.sovereign.enabled = True
    s.on_power_text("Power 95%", 10.0)
    assert s.plan(11.0) == []
    s.on_power_text("Power 80%", 12.0)
    plan = s.plan(13.0)
    assert len(plan) == 1 and plan[0][1].steps[0].value == "Enchant Relic"
    assert s.plan(200.0) == []  # stale reading: do nothing


def test_totem_holds_weather_time_and_surge_with_cooldown():
    s = _svc()
    t = s.cfg.totem
    t.enabled, t.weather, t.time, t.surge = True, "Aurora Borealis", "Night", "Mutation"
    s.on_world_text("Rain Day", 5.0)
    items = [r.steps[0].value for _, r in s.plan(6.0)]
    assert items == ["Aurora Totem", "Sundial Totem", "Mutation Totem"]
    for _, r in s.plan(6.0):
        s.mark(r, 6.0)
    assert s.plan(7.0) == []  # cooldown
    s.on_world_text("Aurora Night mutation surge", 8.0)
    assert s.plan(8.0 + 6 * 60) == []  # everything already as wanted


def test_totem_off_or_none_does_nothing():
    s = _svc()
    s.on_world_text("Rain Day", 1.0)
    assert s.plan(2.0) == []
    s.cfg.totem.enabled = True  # weather "None", time "Auto", surge "None"
    assert s.plan(2.0) == []


def test_potion_and_astral_timers():
    s = _svc()
    s.cfg.potion.enabled = True
    s.cfg.astral.enabled = True
    assert s.plan(60.0) == []
    names = [r.steps[0].value for _, r in s.plan(15 * 60.0)]
    assert names == ["Luck Potion"]
    for _, r in s.plan(15 * 60.0):
        s.mark(r, 15 * 60.0)
    names = [r.steps[0].value for _, r in s.plan(30 * 60.0 + 1)]
    assert names == ["Luck Potion", "Astral Activator"]


def test_appraise_routine_modes():
    s = _svc()
    s.cfg.appraise.traits = ["Shiny", "Mythical"]
    npc = s.appraise_routine()
    assert npc.repeat_until == "Shiny|Mythical" and npc.steps[0].value == "e"
    s.cfg.appraise.mode = "Gamepass"
    assert s.appraise_routine().steps[0].kind == "click_text"


def test_engine_builds_readers_from_settings():
    from fischmacro.automation.engine import AutomationEngine
    st = AppSettings()
    eng = AutomationEngine(st, Profile())
    assert [w.kind for w in eng.active_watchers()] == []
    st.hunts.watched = ["Megalodon", "Kraken", "My Event"]
    st.hunts.custom = ["My Event", "Not ticked"]
    st.addons.totem.enabled = True
    st.addons.sovereign.enabled = True
    st.rod_detect.enabled = True
    ws = eng.active_watchers()
    assert [w.kind for w in ws] == ["hunt", "world", "power", "rod"]
    assert ws[0].keywords == "Megalodon|Kraken|My Event"
    eng._on_watch_text(ws[2], "Power 42%", 1.0)
    assert eng.addons.world.power == 42
