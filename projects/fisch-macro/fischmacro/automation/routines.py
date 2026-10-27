"""Routines: step lists for items, totems, potions, recharging and appraising.

A routine runs only at a safe point (between catches, or on demand while
automation is stopped). Every step goes through the InputController, so pause,
focus loss and the emergency stop interrupt it immediately.
"""
from __future__ import annotations

import copy
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from fischmacro.profiles.schema import LoadoutConfig, Routine, RoutineStep
from fischmacro.vision.ocr import OcrEngine, find_keywords, find_text_box

log = logging.getLogger(__name__)


class RoutineAborted(Exception):
    pass


@dataclass
class RoutineContext:
    input: object
    loadout: LoadoutConfig
    rod_key: str
    to_screen: Callable[[float, float], tuple[int, int]]
    grab: Callable[[], object]              # -> full-client BGR image, or None
    sleep: Callable[[float], object]        # interruptible sleep; returns True if aborted
    emit: Callable[..., None]
    ocr: OcrEngine | None = None


def _keywords(value: str) -> list[str]:
    return [k.strip() for k in value.split("|") if k.strip()]


class RoutineRunner:
    def __init__(self, ctx: RoutineContext):
        self.ctx = ctx

    # -- helpers
    def _wait(self, seconds: float) -> None:
        if self.ctx.sleep(max(0.0, seconds)):
            raise RoutineAborted("stopped")

    def _need_input(self, ok: bool) -> None:
        if not ok:
            raise RoutineAborted("input disabled (paused or emergency stop)")

    def _click(self, x: float, y: float) -> None:
        sx, sy = self.ctx.to_screen(x, y)
        self._need_input(self.ctx.input.click(sx, sy))

    def _ocr(self):
        img = self.ctx.grab()
        if img is None:
            return [], None
        ocr = self.ctx.ocr or OcrEngine.shared()
        return ocr.read(img), img

    # -- steps
    def use_item(self, name: str) -> None:
        lo = self.ctx.loadout
        slot = lo.slot_for(name)
        if slot:
            self._need_input(self.ctx.input.press_key(slot))
            self._wait(0.5)
        else:
            # not on the hotbar: open the inventory, search by name, pick the first result
            self._need_input(self.ctx.input.press_key(lo.inventory_key))
            self._wait(0.6)
            self._click(lo.search_x, lo.search_y)
            self._wait(0.2)
            self._need_input(self.ctx.input.type_text(name, lo.type_delay_ms))
            self._wait(0.7)
            self._click(lo.result_x, lo.result_y)
            self._wait(0.4)
            self._need_input(self.ctx.input.press_key(lo.inventory_key))
            self._wait(0.5)
        if lo.use_click:
            self._click(0.5, 0.5)
            self._wait(0.4)

    def run_step(self, step: RoutineStep) -> None:
        k = step.kind
        inp = self.ctx.input
        if k == "use_item":
            self.use_item(step.value)
        elif k == "equip_rod":
            self._need_input(inp.press_key(self.ctx.rod_key))
            self._wait(0.5)
        elif k == "key":
            self._need_input(inp.press_key(step.value))
        elif k == "type":
            self._need_input(inp.type_text(step.value, self.ctx.loadout.type_delay_ms))
        elif k == "click":
            self._click(step.x, step.y)
        elif k == "wait":
            self._wait(step.seconds)
        elif k == "click_text":
            deadline = time.monotonic() + max(0.5, step.seconds)
            while True:
                boxes, _ = self._ocr()
                box = find_text_box(boxes, step.value)
                if box:
                    self._click(box.x, box.y)
                    return
                if time.monotonic() >= deadline:
                    raise RoutineAborted(f"text '{step.value}' not found on screen")
                self._wait(0.5)
        elif k == "wait_text":
            deadline = time.monotonic() + max(0.5, step.seconds)
            words = _keywords(step.value)
            while True:
                boxes, _ = self._ocr()
                if find_keywords(" ".join(b.text for b in boxes), words):
                    return
                if time.monotonic() >= deadline:
                    raise RoutineAborted(f"none of {words} appeared")
                self._wait(0.6)
        else:
            raise RoutineAborted(f"unknown step '{k}'")

    def run(self, routine: Routine) -> bool:
        """Run a routine. Returns True if it completed."""
        self.ctx.emit("routine", f"Running routine '{routine.name}'")
        stop_words = _keywords(routine.repeat_until)
        try:
            for i in range(max(1, routine.max_repeats)):
                for step in routine.steps:
                    self.run_step(step)
                if stop_words:
                    self._wait(0.4)
                    boxes, _ = self._ocr()
                    found = find_keywords(" ".join(b.text for b in boxes), stop_words)
                    if found:
                        self.ctx.emit("routine", f"'{routine.name}': found {', '.join(found)} after {i + 1} tries")
                        break
                elif routine.max_repeats <= 1:
                    break
            if routine.reequip_rod:
                self._need_input(self.ctx.input.press_key(self.ctx.rod_key))
                self._wait(0.5)
            return True
        except RoutineAborted as exc:
            self.ctx.input.release_all()
            self.ctx.emit("warning", f"Routine '{routine.name}' stopped: {exc}")
            return False


class RoutineScheduler:
    """Decides which routines are due. Watchers queue routines with :meth:`trigger`."""

    def __init__(self) -> None:
        self.last_run: dict[str, float] = {}
        self.catches_at_run: dict[str, int] = {}
        self.pending: set[str] = set()

    def reset(self, now: float, catches: int = 0) -> None:
        self.last_run.clear()
        self.catches_at_run.clear()
        self.pending.clear()
        self._start, self._catches0 = now, catches

    def trigger(self, name: str) -> None:
        self.pending.add(name)

    def due(self, routines: list[Routine], now: float, catches: int) -> list[Routine]:
        out = []
        start = getattr(self, "_start", now)
        for r in routines:
            if not r.enabled or not r.steps:
                continue
            last = self.last_run.get(r.name)
            if last is not None and now - last < r.cooldown_min * 60:
                continue
            ref = last if last is not None else start
            if r.name in self.pending:
                out.append(r)
            elif r.trigger == "interval" and now - ref >= r.interval_min * 60:
                out.append(r)
            elif r.trigger == "catches" and catches - self.catches_at_run.get(r.name, getattr(self, "_catches0", 0)) \
                    >= max(1, r.every_catches):
                out.append(r)
        return out

    def mark_run(self, r: Routine, now: float, catches: int) -> None:
        self.last_run[r.name] = now
        self.catches_at_run[r.name] = catches
        self.pending.discard(r.name)


def _s(kind, value="", seconds=1.0, x=0.5, y=0.5) -> RoutineStep:
    return RoutineStep(kind, value, seconds, x, y)


PRESET_ROUTINES: list[Routine] = [
    Routine("Luck potion", trigger="interval", interval_min=15, steps=[_s("use_item", "Luck Potion"), _s("wait", seconds=1.5)],
            note="Drinks a potion every 15 min. Put the potion on the hotbar or set up the inventory search.",
            verify=True),
    Routine("Totem", trigger="interval", interval_min=15, steps=[_s("use_item", "Aurora Totem"), _s("wait", seconds=6)],
            note="Change the item name to your totem. Some totems only work at certain times - use a watcher "
                 "trigger (e.g. 'Night') so it fires only when it can.", verify=True),
    Routine("Astral Activator", trigger="interval", interval_min=30,
            steps=[_s("use_item", "Astral Activator"), _s("wait", seconds=2)],
            note="Activates the telescope anomaly. Needs batteries/lens set up in game.", verify=True),
    Routine("Sovereign recharge", trigger="watcher", watcher="Rod charge",
            steps=[_s("use_item", "Enchant Relic"), _s("click_text", "Recharge", seconds=4), _s("wait", seconds=2)],
            note="Gamepass recharge with an Enchant Relic. The button names are a guess - edit the steps to match "
                 "what you see. Pair it with a watcher on the rod charge text.", verify=True),
    Routine("Auto appraise (gamepass)", trigger="manual",
            steps=[_s("click_text", "Appraise", seconds=4), _s("wait", seconds=2.5)],
            repeat_until="Shiny|Sparkling|Mythical|Abyssal|Celestial", max_repeats=20, reequip_rod=False,
            note="Hold the fish to appraise, then run. Repeats until one of the wanted mutations shows.", verify=True),
    Routine("Appraiser NPC", trigger="manual",
            steps=[_s("key", "e"), _s("wait", seconds=1.0), _s("click_text", "Appraise", seconds=4),
                   _s("wait", seconds=2.5)],
            repeat_until="Shiny|Sparkling|Mythical", max_repeats=10, reequip_rod=False,
            note="Stand next to the appraiser NPC holding the fish.", verify=True),
]


def preset_copies() -> list[Routine]:
    return [copy.deepcopy(r) for r in PRESET_ROUTINES]
