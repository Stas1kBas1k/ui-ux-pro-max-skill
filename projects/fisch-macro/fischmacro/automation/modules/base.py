"""Extensible game-module API.

Modules hook into the fishing loop without touching the vision engine or the
state machine. They may only send input at *safe points* (between fishing
cycles), so they can never interfere with an active minigame.

To add a module: subclass :class:`GameModule`, declare ``fields``, decorate
with ``@register`` and import it in ``fischmacro/automation/modules/__init__.py``.
The Automation page builds its settings form from ``fields`` automatically.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ModuleField:
    key: str
    label: str
    kind: str = "bool"          # bool | int | float | str | key | choice
    default: Any = False
    min: float | None = None
    max: float | None = None
    help: str = ""
    choices: list[str] | None = None
    experimental: bool = False


@dataclass
class ModuleContext:
    """What a module may use. Built by the state machine for each call."""
    input: Any
    profile: Any
    now: float
    emit: Callable[..., None]
    click_client: Callable[[float, float], bool]
    press_key: Callable[[str], bool]
    sleep: Callable[[float], None]
    request_stop: Callable[[str], None]
    stats: Any = None
    observation: Any = None


class GameModule:
    id: str = ""
    name: str = ""
    description: str = ""
    experimental: bool = False
    fields: list[ModuleField] = []

    def __init__(self, settings: dict):
        self.settings = settings
        for f in [ModuleField("enabled", "Enabled", "bool", False)] + list(self.fields):
            self.settings.setdefault(f.key, f.default)
        self.state: dict[str, Any] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("enabled", False))

    def get(self, key: str) -> Any:
        return self.settings.get(key)

    # hooks -------------------------------------------------------------
    def on_session_start(self, ctx: ModuleContext) -> None: ...
    def on_cycle_complete(self, ctx: ModuleContext, outcome: str) -> None: ...
    def at_safe_point(self, ctx: ModuleContext) -> None: ...
    def on_tick(self, ctx: ModuleContext) -> None: ...


REGISTRY: dict[str, type[GameModule]] = {}


def register(cls: type[GameModule]) -> type[GameModule]:
    if not cls.id:
        raise ValueError("Module needs an id")
    REGISTRY[cls.id] = cls
    return cls


@dataclass
class ModuleHost:
    """Instantiates every registered module with its settings from the profile."""
    modules_settings: dict[str, dict]
    modules: dict[str, GameModule] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for mid, cls in REGISTRY.items():
            settings = self.modules_settings.setdefault(mid, {})
            self.modules[mid] = cls(settings)

    def get(self, mid: str) -> GameModule | None:
        m = self.modules.get(mid)
        return m if m and m.enabled else None

    def enabled(self) -> list[GameModule]:
        return [m for m in self.modules.values() if m.enabled]

    def call(self, hook: str, *args) -> None:
        for m in self.enabled():
            try:
                getattr(m, hook)(*args)
            except Exception:  # noqa: BLE001 - a broken module must not break fishing
                log.exception("Module %s failed in %s", m.id, hook)
