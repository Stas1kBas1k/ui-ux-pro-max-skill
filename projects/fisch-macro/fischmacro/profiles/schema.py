"""Typed configuration schema.

Every tunable value lives in a dataclass field. The ``opt`` helper attaches UI
metadata (label, range, help text, experimental flag) so the settings pages can
be generated from the schema instead of being hand-written per field.
"""
from __future__ import annotations

import copy
import dataclasses
import typing
from dataclasses import dataclass, field
from typing import Any


def opt(default: Any, label: str, help: str = "", *, min: float | None = None,
        max: float | None = None, step: float | None = None, decimals: int | None = None,
        choices: list[str] | None = None, kind: str | None = None,
        experimental: bool = False, suffix: str = "") -> Any:
    """Declare a config field with UI metadata."""
    meta = dict(label=label, help=help, min=min, max=max, step=step, decimals=decimals,
                choices=choices, kind=kind, experimental=experimental, suffix=suffix)
    if isinstance(default, (list, dict, set)) or dataclasses.is_dataclass(default):
        return field(default_factory=lambda d=default: copy.deepcopy(d), metadata=meta)
    return field(default=default, metadata=meta)


# --------------------------------------------------------------------------- regions

@dataclass
class Region:
    """A rectangle in normalised game-client coordinates (0..1).

    Normalising against the Roblox client area makes calibration survive window
    moves, resolution changes and DPI scaling.
    """
    x: float = 0.0
    y: float = 0.0
    w: float = 0.1
    h: float = 0.1
    enabled: bool = True

    def to_rect(self, client_w: int, client_h: int) -> tuple[int, int, int, int]:
        x = int(round(self.x * client_w))
        y = int(round(self.y * client_h))
        w = max(1, int(round(self.w * client_w)))
        h = max(1, int(round(self.h * client_h)))
        x = min(max(0, x), max(0, client_w - 1))
        y = min(max(0, y), max(0, client_h - 1))
        w = min(w, client_w - x)
        h = min(h, client_h - y)
        return x, y, max(1, w), max(1, h)

    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2

    def is_valid(self) -> bool:
        return self.w > 0.001 and self.h > 0.001 and 0 <= self.x <= 1 and 0 <= self.y <= 1


REGION_LABELS = {
    "reel": "Reel minigame bar",
    "progress": "Catch progress bar",
    "shake": "Shake prompt area",
    "cast": "Cast power bar",
    "catch_popup": "Catch result popup",
    "disconnect": "Disconnect dialog",
    "reconnect_button": "Reconnect button",
}

# Defaults approximate the Fisch layout at 16:9 and are expected to be calibrated.
DEFAULT_REGIONS = {
    "reel": Region(0.285, 0.835, 0.43, 0.045),
    "progress": Region(0.38, 0.895, 0.24, 0.016),
    "shake": Region(0.15, 0.15, 0.70, 0.62),
    "cast": Region(0.525, 0.30, 0.03, 0.26),
    "catch_popup": Region(0.30, 0.10, 0.40, 0.14, enabled=False),
    "disconnect": Region(0.30, 0.30, 0.40, 0.40),
    "reconnect_button": Region(0.52, 0.60, 0.12, 0.05, enabled=False),
}


# --------------------------------------------------------------------------- profile sections

@dataclass
class DetectionConfig:
    fish_color: str = opt("#434B5B", "Fish indicator colour", "Colour of the fish icon inside the reel bar.", kind="color")
    fish_tolerance: int = opt(22, "Fish colour tolerance", "Per-channel tolerance (0-255).", min=0, max=128)
    bar_color: str = opt("#F1F1F1", "Catch bar colour", "Colour of the player-controlled catch bar.", kind="color")
    bar_tolerance: int = opt(24, "Catch bar tolerance", min=0, max=128)
    bar_column_fill: float = opt(0.35, "Bar column fill", "Fraction of a column that must match to count as bar.", min=0.05, max=1.0, step=0.05, decimals=2)
    bar_min_width: float = opt(0.04, "Minimum bar width", "Relative to the reel region width.", min=0.01, max=0.9, step=0.01, decimals=2)
    progress_color: str = opt("#FFFFFF", "Progress fill colour", kind="color")
    progress_tolerance: int = opt(40, "Progress tolerance", min=0, max=128)
    shake_color: str = opt("#F0F0F0", "Shake button colour", kind="color")
    shake_tolerance: int = opt(28, "Shake tolerance", min=0, max=128)
    shake_min_area: float = opt(0.0015, "Shake min area", "Fraction of the shake region.", min=0.0001, max=0.2, step=0.0005, decimals=4)
    shake_max_area: float = opt(0.06, "Shake max area", min=0.001, max=0.5, step=0.005, decimals=3)
    shake_template: str = opt("", "Shake template image", "Optional PNG captured from the game. Overrides colour detection.", kind="path")
    shake_template_ref_h: int = opt(0, "Template reference height", "Client height when the template was captured.", min=0, max=10000)
    template_threshold: float = opt(0.72, "Template match threshold", min=0.3, max=0.99, step=0.01, decimals=2)
    cast_color: str = opt("#46D246", "Cast power fill colour", kind="color")
    cast_tolerance: int = opt(70, "Cast colour tolerance", min=0, max=160)
    cast_orientation: str = opt("vertical", "Cast bar orientation", choices=["vertical", "horizontal"])
    auto_adapt: bool = opt(True, "Auto-adapt to rod / skin changes", "When the minigame is not recognised, find it and "
                           "re-sample its colours automatically (saved to the profile).")
    min_confidence: float = opt(0.5, "Minimum detection confidence", "Below this a detection is ignored.", min=0.05, max=0.99, step=0.05, decimals=2)
    disconnect_detection: bool = opt(True, "Detect disconnect dialogs")
    dialog_color: str = opt("#393B3D", "Dialog background colour", kind="color", experimental=True)
    dialog_tolerance: int = opt(14, "Dialog tolerance", min=0, max=64, experimental=True)
    dialog_min_fill: float = opt(0.55, "Dialog min fill", min=0.1, max=1.0, step=0.05, decimals=2, experimental=True)
    catch_template: str = opt("", "Catch popup template", "Optional PNG of the catch notification.", kind="path", experimental=True)
    catch_template_ref_h: int = opt(0, "Catch template reference height", min=0, max=10000)


@dataclass
class CastingConfig:
    mode: str = opt("perfect", "Cast mode", "'perfect' releases when the power bar is full; 'timed' uses a fixed hold; "
                    "'normal' is a short casual cast right after each catch.", choices=["perfect", "timed", "normal"])
    normal_hold: float = opt(0.3, "Normal cast hold", "Hold time in normal mode.", min=0.05, max=2.0, step=0.05,
                             decimals=2, suffix=" s")
    jitter: float = opt(0.15, "Timing jitter", "Random +/- fraction applied to cast hold and delay so casts are not "
                        "machine-regular.", min=0.0, max=0.5, step=0.05, decimals=2)
    hold_seconds: float = opt(0.95, "Cast hold time", "Used in timed mode, and as fallback when the power bar is not seen.", min=0.05, max=5.0, step=0.05, decimals=2, suffix=" s")
    perfect_threshold: float = opt(0.95, "Perfect cast threshold", "Release once the power bar is at least this full.", min=0.5, max=1.0, step=0.01, decimals=2, experimental=True)
    max_hold_seconds: float = opt(3.0, "Max cast hold", "Safety limit: always release after this long.", min=0.5, max=10.0, step=0.1, decimals=1, suffix=" s")
    pre_cast_delay: float = opt(0.35, "Delay before cast", min=0.0, max=5.0, step=0.05, decimals=2, suffix=" s")
    move_mouse_to_center: bool = opt(True, "Move cursor to game centre before casting")


@dataclass
class ShakeConfig:
    mode: str = opt("click", "Shake mode", "'click' finds and clicks shake buttons; 'navigation' uses Roblox UI navigation keys.", choices=["click", "navigation"])
    click_interval: float = opt(0.07, "Min time between clicks", min=0.0, max=1.0, step=0.01, decimals=2, suffix=" s")
    persistence_frames: int = opt(2, "Frames before clicking", "A target must be seen in this many consecutive frames.", min=1, max=10)
    cooldown_radius: float = opt(0.035, "Re-click radius", "Ignore targets this close to a recent click.", min=0.0, max=0.3, step=0.005, decimals=3)
    cooldown_seconds: float = opt(0.35, "Re-click cooldown", min=0.0, max=3.0, step=0.05, decimals=2, suffix=" s")
    nav_toggle_key: str = opt("\\", "Navigation toggle key", kind="key")
    nav_confirm_key: str = opt("enter", "Navigation confirm key", kind="key")
    nav_press_interval: float = opt(0.12, "Navigation press interval", min=0.03, max=2.0, step=0.01, decimals=2, suffix=" s")
    nav_start_delay: float = opt(0.8, "Navigation start delay", "Wait after casting before pressing keys.", min=0.0, max=10.0, step=0.1, decimals=1, suffix=" s")


@dataclass
class ReelConfig:
    mode: str = opt("standard", "Tracking mode", "'precision' plans ahead with a learned model of the bar - best for "
                    "tryhard / low-resilience rods with a tiny bar. Falls back to standard until the model is learned "
                    "(a few seconds of reeling).", choices=["standard", "precision"])
    mpc_horizon: float = opt(0.4, "Precision look-ahead", "How far ahead precision mode plans.", min=0.15, max=1.0,
                             step=0.05, decimals=2, suffix=" s")
    mpc_margin: float = opt(0.15, "Precision safety margin", "Keeps the fish this far inside the bar edges (fraction of "
                            "bar width).", min=0.0, max=0.45, step=0.05, decimals=2)
    kp: float = opt(3.0, "Response strength (Kp)", "Proportional gain on fish/bar error.", min=0.0, max=20.0, step=0.1, decimals=2)
    kd: float = opt(0.45, "Damping (Kd)", "Derivative gain; reduces overshoot.", min=0.0, max=5.0, step=0.05, decimals=2)
    feedforward: float = opt(0.25, "Velocity feed-forward", "Adds fish velocity to the command.", min=0.0, max=3.0, step=0.05, decimals=2)
    lookahead: float = opt(0.08, "Prediction look-ahead", "Seconds of fish motion to predict.", min=0.0, max=0.5, step=0.01, decimals=2, suffix=" s")
    smoothing: float = opt(0.5, "Velocity smoothing", "0 = raw, 0.95 = very smooth.", min=0.0, max=0.95, step=0.05, decimals=2)
    hold_bias: float = opt(0.5, "Hover duty", "Fraction of time held that keeps the bar still (rod dependent).", min=0.05, max=0.95, step=0.01, decimals=2)
    auto_hover: bool = opt(True, "Auto-tune hover duty", "Learns the rod's hover duty from how the bar responds while reeling. "
                           "Starts from the value above and adapts within a few seconds.")
    edge_margin: float = opt(0.07, "Edge margin", "Near an edge the bar is driven fully toward it.", min=0.0, max=0.3, step=0.01, decimals=2)
    max_hold_seconds: float = opt(3.0, "Max continuous hold", "Safety limit on holding the mouse.", min=0.2, max=15.0, step=0.1, decimals=1, suffix=" s")
    min_confidence: float = opt(0.45, "Reel min confidence", "Below this the mouse is released.", min=0.05, max=0.99, step=0.05, decimals=2)
    end_grace: float = opt(0.6, "Minigame end grace", "Reel bar must be gone this long to count as ended.", min=0.1, max=5.0, step=0.1, decimals=1, suffix=" s")
    lost_fish_timeout: float = opt(1.2, "Lost fish timeout", "Release if the fish is not seen this long.", min=0.1, max=10.0, step=0.1, decimals=1, suffix=" s")
    success_threshold: float = opt(0.75, "Success progress", "Progress at end above this counts as a catch.", min=0.3, max=1.0, step=0.05, decimals=2)
    fail_threshold: float = opt(0.2, "Failure progress", "Progress at end below this counts as a failure.", min=0.0, max=0.7, step=0.05, decimals=2)


@dataclass
class TimingConfig:
    bite_timeout: float = opt(45.0, "Bite timeout", "Recast if nothing bites within this time.", min=3.0, max=600.0, step=1.0, decimals=0, suffix=" s")
    shake_timeout: float = opt(25.0, "Shake timeout", min=2.0, max=300.0, step=1.0, decimals=0, suffix=" s")
    reel_timeout: float = opt(120.0, "Reel timeout", min=5.0, max=600.0, step=5.0, decimals=0, suffix=" s")
    post_catch_delay: float = opt(1.6, "Delay after catch", min=0.0, max=30.0, step=0.1, decimals=1, suffix=" s")
    recovery_delay: float = opt(2.0, "Recovery delay", min=0.0, max=60.0, step=0.5, decimals=1, suffix=" s")
    max_consecutive_recoveries: int = opt(5, "Max recoveries in a row", "Exceeding this stops automation with an error.", min=1, max=100)
    capture_failure_limit: int = opt(30, "Capture failures before error", min=1, max=1000)
    recovery_click: bool = opt(True, "Click once during recovery", "Reels the line back in after a timeout so the next cast starts clean.")


@dataclass
class EquipmentConfig:
    rod_name: str = opt("Any rod", "Rod name", "For your reference; tune the reel controller per rod.")
    rod_slot_key: str = opt("1", "Rod hotbar key", kind="key")
    equip_before_cast: bool = opt(False, "Press rod key before every cast")
    reequip_on_recovery: bool = opt(False, "Re-equip rod during recovery", "Presses the rod key twice (unequip + equip). Only enable if that resets your rod.")


@dataclass
class Profile:
    name: str = "Default"
    notes: str = ""
    regions: dict[str, Region] = field(default_factory=lambda: copy.deepcopy(DEFAULT_REGIONS))
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    casting: CastingConfig = field(default_factory=CastingConfig)
    shake: ShakeConfig = field(default_factory=ShakeConfig)
    reel: ReelConfig = field(default_factory=ReelConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    equipment: EquipmentConfig = field(default_factory=EquipmentConfig)
    modules: dict[str, dict] = field(default_factory=dict)

    def region(self, name: str) -> Region:
        if name not in self.regions:
            self.regions[name] = copy.deepcopy(DEFAULT_REGIONS.get(name, Region(enabled=False)))
        return self.regions[name]


# --------------------------------------------------------------------------- app settings

HOTKEY_ACTIONS = {
    "start": "Start automation",
    "pause": "Pause / resume",
    "stop": "Emergency stop",
    "overlay": "Toggle debug overlay",
    "calibrate": "Open / close calibration",
    "snapshot": "Diagnostic snapshot",
}


@dataclass
class HotkeyConfig:
    start: str = "f6"
    pause: str = "f7"
    stop: str = "f8"
    overlay: str = "f9"
    calibrate: str = "f10"
    snapshot: str = "f11"

    def as_dict(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in HOTKEY_ACTIONS}


@dataclass
class CaptureConfig:
    mode: str = opt("window", "Capture source", "'window' follows the Roblox window, 'monitor' captures a whole monitor, 'simulation' uses the built-in test game (no real input).", choices=["window", "monitor", "simulation"])
    window_title: str = opt("Roblox", "Game window title")
    monitor: int = opt(1, "Monitor index", "Used in monitor mode (1 = primary).", min=1, max=8)
    require_focus: bool = opt(True, "Only send input while Roblox is focused", "Strongly recommended. Inputs are paused when you alt-tab.")
    window_lost_timeout: float = opt(20.0, "Window lost timeout", "Stop with an error if the game window is missing this long.", min=1.0, max=600.0, step=1.0, decimals=0, suffix=" s")


@dataclass
class PerformanceConfig:
    detection_fps: int = opt(40, "Detection FPS limit", min=5, max=144)
    reel_fps: int = opt(90, "Reel minigame FPS", "Capture rate while reeling. Higher reacts faster to the fish.", min=20, max=240)
    preview_fps: int = opt(10, "Preview FPS", "Live preview refresh rate in the UI.", min=1, max=30)
    roi_capture: bool = opt(True, "Capture only needed regions", "Greatly reduces CPU usage.")
    full_check_interval: float = opt(2.0, "Full-frame check interval", "How often disconnect checks run.", min=0.25, max=30.0, step=0.25, decimals=2, suffix=" s")


@dataclass
class InputConfig:
    click_hold_ms: int = opt(25, "Click hold", min=1, max=500, suffix=" ms")
    key_hold_ms: int = opt(35, "Key hold", min=1, max=500, suffix=" ms")
    mouse_nudge: bool = opt(True, "Nudge cursor before clicks", "Roblox sometimes ignores clicks without a preceding mouse move.")
    min_switch_interval_ms: int = opt(0, "Min reel input switch interval", "0 = switch every frame if needed.", min=0, max=200, suffix=" ms")


@dataclass
class StartupConfig:
    start_preview_on_launch: bool = opt(False, "Start vision preview on launch", "Automation itself never starts on launch.")
    start_minimized: bool = opt(False, "Start minimised")
    remember_geometry: bool = opt(True, "Remember window size and position")
    confirm_exit_while_running: bool = opt(True, "Confirm exit while automation runs")


@dataclass
class LoggingConfig:
    level: str = opt("INFO", "Log level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    snapshot_on_error: bool = opt(True, "Save a screenshot on errors", "Stored locally in the diagnostics folder.")
    max_log_files: int = opt(5, "Rotated log files to keep", min=1, max=50)


@dataclass
class AppearanceConfig:
    theme: str = opt("Midnight Violet", "Theme", choices=["Midnight Violet", "Deep Ocean", "Abyss Emerald", "Coral Reef",
                                                         "Arctic Light", "High Contrast"])
    text_size: str = opt("Comfortable", "Text size", choices=["Compact", "Comfortable", "Large"])
    reduce_motion: bool = opt(False, "Reduce motion", "Disables pulsing indicators and toast animations.")
    show_artwork: bool = opt(True, "Show artwork banner on the dashboard")


@dataclass
class NotificationsConfig:
    toasts: bool = opt(True, "In-app toast messages", "Short pop-ups for errors, reminders and session events.")
    tray_icon: bool = opt(True, "Show tray icon", "Start / pause / stop from the Windows notification area.")
    minimize_to_tray: bool = opt(False, "Minimise to tray")
    desktop_notifications: bool = opt(True, "Desktop notifications", "Tray balloons for errors, disconnects and reminders.")
    notify_every_catches: int = opt(0, "Notify every N catches", "0 = off.", min=0, max=1000)
    sound_on_error: bool = opt(True, "Sound on errors and disconnects")


@dataclass
class AppSettings:
    active_profile: str = "Default"
    risk_acknowledged: bool = False
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    input: InputConfig = field(default_factory=InputConfig)
    startup: StartupConfig = field(default_factory=StartupConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    window_geometry: str = ""
    setup_dismissed: bool = False
    setup_progress: dict[str, bool] = field(default_factory=dict)  # milestones seen in the live game
    overlay_enabled: bool = False


# --------------------------------------------------------------------------- (de)serialisation

def to_dict(obj: Any) -> Any:
    return dataclasses.asdict(obj)


def from_dict(cls: type, data: Any) -> Any:
    """Build ``cls`` from ``data``, ignoring unknown keys and filling missing ones.

    Tolerant on purpose so older or hand-edited profile files still load.
    """
    if not isinstance(data, dict):
        return cls()
    hints = typing.get_type_hints(cls)
    obj = cls()
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        setattr(obj, f.name, _convert(hints[f.name], data[f.name], getattr(obj, f.name)))
    return obj


def _convert(tp: Any, value: Any, default: Any) -> Any:
    origin = typing.get_origin(tp)
    if dataclasses.is_dataclass(tp):
        return from_dict(tp, value)
    if origin is dict:
        _, vt = typing.get_args(tp)
        if not isinstance(value, dict):
            return default
        if dataclasses.is_dataclass(vt):
            merged = dict(default) if isinstance(default, dict) else {}
            merged.update({str(k): from_dict(vt, v) for k, v in value.items()})
            return merged
        return dict(value)
    if tp is bool:
        return bool(value)
    if tp is int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    if tp is float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    if tp is str:
        return str(value)
    return value


def field_meta(cls: type) -> list[tuple[str, dict]]:
    """(name, metadata) for every UI-annotated field of a config dataclass."""
    return [(f.name, dict(f.metadata)) for f in dataclasses.fields(cls) if "label" in f.metadata]
