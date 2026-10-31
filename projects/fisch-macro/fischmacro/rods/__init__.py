"""Rod behaviours: one module per special rod, plus what the UI needs to know about each.

Standard reeling (fish tracking + bar control) is the same for every rod and lives in
``automation.fsm`` / ``automation.tracking`` / ``automation.reel_controller``. A behaviour only adds what
its rod does on top: extra inputs (Lullaby clicks, MiguRod key), a filter on the observation (Halibut),
and which settings matter for it. Adding a rod = one new module + one entry here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from fischmacro.rods import halibut, lullaby, migu, stellarwave, targets


@dataclass(frozen=True)
class RodBehaviour:
    kind: str                       # MinigameConfig.kind
    label: str
    summary: str
    update: Callable | None = None       # (solver, obs, now) each reeling frame
    filter_obs: Callable | None = None   # (solver, obs, now) before steering
    settings: tuple[str, ...] = ()       # MinigameConfig fields that matter for this rod (simple view)
    advanced: tuple[str, ...] = ()       # technical fields (advanced view)
    events: tuple[str, ...] = ()         # on-screen events it handles
    status: str = "simulated"            # "real screenshot" | "simulated" | "unconfirmed"
    notes: list[str] = field(default_factory=list)


ROD_BEHAVIOURS: dict[str, RodBehaviour] = {b.kind: b for b in (
    RodBehaviour("none", "Standard", "Reels: keeps the fish inside the bar.",
                 status="real screenshot"),
    RodBehaviour("lullaby", "Lullaby", "Clicks the metronome only over lit sections; switches the mode once per Start.",
                 lullaby.update, settings=("lullaby_mode", "keep_reeling"),
                 advanced=("lead_ms", "min_interval", "mode_key", "pointer_tolerance", "lit_tolerance"),
                 events=("lit section under the pendulum",), status="simulated",
                 notes=["Input delay is learned from hits."]),
    RodBehaviour("stellarwave", "Stellarwave sign picker", "Clicks the asked zodiac sign and checks the click "
                 "(experimental: how a sign is picked is not confirmed).",
                 stellarwave.update, settings=("keep_reeling",), advanced=("match_threshold", "symbol_tolerance"),
                 events=("zodiac sign asked",), status="unconfirmed"),
    RodBehaviour("migu", "MiguRod", "Presses the key shown on the counterattack bar (Shift) when the line is "
                 "on the diamond.", migu.update, settings=("migu_key", "keep_reeling"),
                 advanced=("migu_window", "lead_ms"), events=("counterattack bar", "key prompt"),
                 status="real screenshot", notes=["Slash dodging is not automated (mechanic not documented)."]),
    RodBehaviour("halibut", "Halibut Harpoon", "Nothing to press; ignores the '!' icon so the bar is not pulled away.",
                 filter_obs=halibut.filter_obs, settings=("keep_reeling",), advanced=("halibut_gun_key",),
                 events=("'!' harpoon mark",), status="real screenshot"),
    RodBehaviour("targets", "Target clicker", "Clicks coloured targets (generic, experimental).",
                 targets.update, advanced=("target_color", "target_tolerance", "target_interval"),
                 events=("coloured target",), status="simulated"),
)}


def behaviour_for(kind: str) -> RodBehaviour:
    return ROD_BEHAVIOURS.get(kind, ROD_BEHAVIOURS["none"])
