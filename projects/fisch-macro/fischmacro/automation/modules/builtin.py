"""Built-in modules."""
from __future__ import annotations

from fischmacro.automation.modules.base import GameModule, ModuleContext, ModuleField, register


@register
class SessionLimitsModule(GameModule):
    id = "session_limits"
    name = "Session limits"
    description = "Stop automatically after a number of catches, minutes, or failures in a row."
    fields = [
        ModuleField("max_catches", "Stop after catches (0 = off)", "int", 0, 0, 100000),
        ModuleField("max_minutes", "Stop after minutes (0 = off)", "int", 0, 0, 10000),
        ModuleField("max_failures_in_row", "Stop after failures in a row (0 = off)", "int", 5, 0, 1000),
    ]

    def on_session_start(self, ctx: ModuleContext) -> None:
        self.state.update(started=ctx.now, catches=0, fails_in_row=0)

    def on_cycle_complete(self, ctx: ModuleContext, outcome: str) -> None:
        if outcome == "success":
            self.state["catches"] = self.state.get("catches", 0) + 1
            self.state["fails_in_row"] = 0
        elif outcome == "failure":
            self.state["fails_in_row"] = self.state.get("fails_in_row", 0) + 1
        mc, mf = int(self.get("max_catches")), int(self.get("max_failures_in_row"))
        if mc and self.state["catches"] >= mc:
            ctx.request_stop(f"Session limit reached: {mc} catches")
        elif mf and self.state["fails_in_row"] >= mf:
            ctx.request_stop(f"Stopped after {mf} failed catches in a row - check calibration")

    def on_tick(self, ctx: ModuleContext) -> None:
        mm = int(self.get("max_minutes"))
        if mm and ctx.now - self.state.get("started", ctx.now) >= mm * 60:
            ctx.request_stop(f"Session limit reached: {mm} minutes")


@register
class TimedActionsModule(GameModule):
    id = "timed_actions"
    name = "Timed actions"
    description = "Press keys on a schedule between catches (e.g. eat food, use a buff item)."
    fields = [
        ModuleField("action1_key", "Action 1 key", "key", ""),
        ModuleField("action1_minutes", "Action 1 every (minutes)", "float", 10.0, 0.1, 600),
        ModuleField("action1_click", "Click after action 1 key", "bool", True),
        ModuleField("action2_key", "Action 2 key", "key", ""),
        ModuleField("action2_minutes", "Action 2 every (minutes)", "float", 30.0, 0.1, 600),
        ModuleField("action2_click", "Click after action 2 key", "bool", True),
        ModuleField("reequip_rod", "Re-equip rod afterwards", "bool", True),
    ]

    def on_session_start(self, ctx: ModuleContext) -> None:
        self.state["last"] = {1: ctx.now, 2: ctx.now}

    def due(self, now: float) -> list[int]:
        out = []
        for i in (1, 2):
            key = self.get(f"action{i}_key")
            if key and now - self.state.get("last", {}).get(i, now) >= float(self.get(f"action{i}_minutes")) * 60:
                out.append(i)
        return out

    def at_safe_point(self, ctx: ModuleContext) -> None:
        did = False
        for i in self.due(ctx.now):
            key = self.get(f"action{i}_key")
            ctx.emit("module", f"Timed action {i}: pressing '{key}'")
            ctx.press_key(key)
            ctx.sleep(0.4)
            if self.get(f"action{i}_click"):
                ctx.click_client(0.5, 0.5)
                ctx.sleep(1.2)
            self.state["last"][i] = ctx.now
            did = True
        if did and self.get("reequip_rod"):
            ctx.press_key(ctx.profile.equipment.rod_slot_key)
            ctx.sleep(0.5)


@register
class TotemModule(GameModule):
    id = "totem"
    name = "Totem / item reminder"
    description = "Reminds you when a totem or timed item is due. Optional activation routine (experimental)."
    fields = [
        ModuleField("minutes", "Remind every (minutes)", "float", 15.0, 0.5, 1440),
        ModuleField("label", "Item name", "str", "Totem"),
        ModuleField("activate", "Activate automatically", "bool", False, experimental=True,
                    help="Presses the item key, clicks to use it and re-equips the rod. Untested against every totem."),
        ModuleField("item_key", "Item hotbar key", "key", "2"),
        ModuleField("use_wait", "Wait after use (seconds)", "float", 3.0, 0.0, 30.0),
    ]

    def on_session_start(self, ctx: ModuleContext) -> None:
        self.state["last"] = ctx.now
        self.state["reminded"] = False

    def is_due(self, now: float) -> bool:
        return now - self.state.get("last", now) >= float(self.get("minutes")) * 60

    def on_tick(self, ctx: ModuleContext) -> None:
        if self.is_due(ctx.now) and not self.state.get("reminded"):
            self.state["reminded"] = True
            ctx.emit("reminder", f"{self.get('label')} is due")

    def at_safe_point(self, ctx: ModuleContext) -> None:
        if not (self.is_due(ctx.now) and self.get("activate")):
            return
        ctx.emit("module", f"Activating {self.get('label')}")
        ctx.press_key(self.get("item_key"))
        ctx.sleep(0.6)
        ctx.click_client(0.5, 0.5)
        ctx.sleep(float(self.get("use_wait")))
        ctx.press_key(ctx.profile.equipment.rod_slot_key)
        ctx.sleep(0.6)
        self.state["last"] = ctx.now
        self.state["reminded"] = False


@register
class AutoReconnectModule(GameModule):
    id = "auto_reconnect"
    name = "Auto reconnect"
    description = ("When a disconnect dialog is detected, click the calibrated Reconnect button and resume. "
                   "Requires the 'Reconnect button' region to be calibrated.")
    experimental = True
    fields = [
        ModuleField("delay", "Wait before clicking (seconds)", "float", 3.0, 0.0, 120.0),
        ModuleField("timeout", "Give up after (seconds)", "float", 90.0, 5.0, 900.0),
        ModuleField("max_attempts", "Max reconnect attempts per session", "int", 3, 1, 50),
    ]
