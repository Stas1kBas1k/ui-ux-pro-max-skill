"""Routines: item use via hotbar and inventory search, OCR clicks, repeat-until, scheduling."""
import pytest

from fischmacro.automation.routines import PRESET_ROUTINES, RoutineContext, RoutineRunner, RoutineScheduler
from fischmacro.input.controller import InputController
from fischmacro.profiles.schema import LoadoutConfig, Routine, RoutineStep
from fischmacro.simulation.game import SimulatedFischGame, SimulatedInputBackend
from fischmacro.vision.ocr import OcrEngine


def runner_for(game, loadout=None, events=None):
    inputs = InputController(SimulatedInputBackend(game), click_hold_ms=0, key_hold_ms=0, mouse_nudge=False)
    ev = events if events is not None else []
    ctx = RoutineContext(
        input=inputs, loadout=loadout or LoadoutConfig(), rod_key="1",
        to_screen=lambda x, y: (int(x * game.width), int(y * game.height)),
        grab=game.render, sleep=lambda s: (game.step(s), False)[1],
        emit=lambda kind, msg, **d: ev.append((kind, msg)))
    return RoutineRunner(ctx), inputs


def test_use_item_from_hotbar_slot_then_reequip():
    g = SimulatedFischGame(seed=1)
    g.slots["2"] = "Luck Potion"
    lo = LoadoutConfig()
    lo.slots["2"] = "Luck Potion"
    runner, _ = runner_for(g, lo)
    assert runner.run(Routine("potion", steps=[RoutineStep("use_item", "Luck Potion")]))
    assert g.items_used == {"Luck Potion": 1}
    assert g.equipped == "Rod"


def test_use_item_through_inventory_search():
    g = SimulatedFischGame(seed=1)
    runner, _ = runner_for(g)
    assert runner.run(Routine("totem", steps=[RoutineStep("use_item", "Aurora Totem")]))
    assert g.items_used == {"Aurora Totem": 1}
    assert not g.inventory_open and g.equipped == "Rod"


def test_stop_aborts_and_releases():
    g = SimulatedFischGame(seed=1)
    runner, inputs = runner_for(g)
    inputs.disable()
    assert not runner.run(Routine("x", steps=[RoutineStep("key", "e")]))


ocr = pytest.mark.skipif(not OcrEngine.shared().available, reason="OCR engine not installed")


@ocr
def test_click_text_and_repeat_until_mutation():
    g = SimulatedFischGame(seed=4)
    g.appraise_ui = True
    events = []
    runner, _ = runner_for(g, events=events)
    r = Routine("appraise", steps=[RoutineStep("click_text", "Appraise", seconds=3), RoutineStep("wait", seconds=0.5)],
                repeat_until="Shiny|Sparkling", max_repeats=25, reequip_rod=False)
    assert runner.run(r)
    assert g.appraise_result in ("Shiny", "Sparkling")
    assert any("found" in m for _, m in events)


@ocr
def test_click_text_missing_fails_cleanly():
    g = SimulatedFischGame(seed=4)
    runner, _ = runner_for(g)
    assert not runner.run(Routine("x", steps=[RoutineStep("click_text", "Nonexistent Button", seconds=0.5)]))


def test_scheduler_triggers():
    s = RoutineScheduler()
    s.reset(0.0, 0)
    timed = Routine("timed", enabled=True, trigger="interval", interval_min=1, steps=[RoutineStep()])
    every = Routine("every", enabled=True, trigger="catches", every_catches=3, steps=[RoutineStep()])
    watch = Routine("watch", enabled=True, trigger="watcher", watcher="Hunt", steps=[RoutineStep()])
    off = Routine("off", enabled=False, trigger="interval", interval_min=0, steps=[RoutineStep()])
    rs = [timed, every, watch, off]
    assert s.due(rs, 30, 1) == []
    assert [r.name for r in s.due(rs, 61, 3)] == ["timed", "every"]
    s.mark_run(timed, 61, 3)
    s.mark_run(every, 61, 3)
    assert s.due(rs, 70, 4) == []
    s.trigger("watch")
    assert [r.name for r in s.due(rs, 71, 4)] == ["watch"]


def test_presets_are_disabled_and_marked_verify():
    assert PRESET_ROUTINES and all(not r.enabled and r.verify for r in PRESET_ROUTINES)
    names = {r.name for r in PRESET_ROUTINES}
    assert {"Totem", "Astral Activator", "Sovereign recharge", "Auto appraise (gamepass)"} <= names


def test_routine_runs_between_catches_during_automation():
    import time

    from fischmacro.automation.engine import AutomationEngine
    from fischmacro.profiles.schema import AppSettings, Profile
    from fischmacro.vision.capture import SimulationCapture
    g = SimulatedFischGame(seed=2)
    g.slots["2"] = "Luck Potion"
    s = AppSettings()
    s.loadout.slots["2"] = "Luck Potion"
    s.routines = [Routine("potion", enabled=True, trigger="catches", every_catches=1, cooldown_min=0,
                          steps=[RoutineStep("use_item", "Luck Potion")])]
    eng = AutomationEngine(s, Profile(), source=SimulationCapture(g),
                           inputs=InputController(SimulatedInputBackend(g), 0, 0, False))
    try:
        eng.start_automation()
        end = time.time() + 60
        while time.time() < end and eng.session.catches < 2:
            time.sleep(0.1)
        assert eng.session.catches >= 2
        assert g.items_used.get("Luck Potion", 0) >= 1
        assert g.stats.catches >= 2  # fishing carried on after the routine
    finally:
        eng.shutdown()
