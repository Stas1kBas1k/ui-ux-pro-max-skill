"""Game modules. Importing this package registers the built-in modules."""
from fischmacro.automation.modules import builtin  # noqa: F401
from fischmacro.automation.modules.base import REGISTRY, GameModule, ModuleContext, ModuleField, ModuleHost, register

__all__ = ["REGISTRY", "GameModule", "ModuleContext", "ModuleField", "ModuleHost", "register"]
