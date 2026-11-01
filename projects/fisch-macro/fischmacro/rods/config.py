"""Per-rod configuration: what each rod is, and which settings its editor shows.

A rod's *definition* is: its behaviour module (``rods/<module>.py``), its detection profile (how its reel is
read), its recommended tracking settings, and which settings matter for it - split into **simple** (shown
to everyone) and **advanced** (behind "Advanced"). Profiles store the full settings; a definition is what
"Reset to recommended" goes back to (``profiles.library.RodLibrary.recommended``).

The editor (web UI) is generated from ``editor_schema(profile)``: sections of fields with labels, help,
types and limits taken from the settings' own metadata (``profiles.schema.opt``). Unknown rods use the
normal reel definition, so every rod is configurable.
"""
from __future__ import annotations

from dataclasses import dataclass, fields as dc_fields
from typing import Any

from fischmacro.profiles.rod_presets import find_preset
from fischmacro.profiles.schema import Profile, field_meta
from fischmacro.rods import STATUS_TEXT, behaviour_for

SENSITIVITY = "reel.sensitivity"   # virtual field: one slider for the controller's gains


# Sensitivity 1-10 sets the controller gains and the shortest hold / release. 5 (the default) is calm:
# about 6 clicks a second in the test game instead of 11-14; 10 is the old, twitchier default.
def _gain(s: int) -> float:
    return 0.4 + 0.06 * s


def sensitivity(profile: Profile) -> int:
    return max(1, min(10, round((profile.reel.kp / 3.0 - 0.4) / 0.06)))


def set_sensitivity(profile: Profile, s: int) -> None:
    s = max(1, min(10, int(s)))
    k = _gain(s)
    r = profile.reel
    r.kp, r.kd, r.feedforward = round(3.0 * k, 2), round(0.45 * k, 2), round(0.25 * k, 2)
    r.min_switch_ms = max(0, 100 - 10 * s)


@dataclass(frozen=True)
class RodDefinition:
    name: str
    behaviour: str                 # MinigameConfig.kind -> rods/<module>.py
    reel_layout: str               # DetectionConfig.reel_mode: "standard" | "capsule"
    note: str
    status: str                    # "real recording" | "real screenshot" | "simulated" | "unconfirmed"
    special: bool

    @property
    def label(self) -> str:
        return behaviour_for(self.behaviour).label


def definition(rod: str) -> RodDefinition:
    """The definition of any rod name (rods without their own entry use the normal reel)."""
    p = Profile()
    pre = find_preset(rod) if rod else None
    if pre is not None:
        from fischmacro.profiles.rod_presets import apply_preset
        apply_preset(p, pre)
    b = behaviour_for(p.minigame.kind)
    status = {"stellarwave": "real recording", "lullaby": "real recording", "migu": "real recording",
              "halibut": "real screenshot"}.get(p.minigame.kind, "real recording")
    return RodDefinition(rod or "Any rod", p.minigame.kind, p.detection.reel_mode,
                         pre.note if pre else "Normal reel: keeps the fish inside the bar.", status, b.kind != "none")


# --- the editor -------------------------------------------------------------------------------------
# (section title, [(path, simple?)]) - minigame fields are added from the rod's behaviour
BASE_SECTIONS: list[tuple[str, list[tuple[str, bool]]]] = [
    ("Fish tracking", [("reel.mode", True), (SENSITIVITY, True), ("reel.mpc_margin", False),
                       ("reel.lookahead", False), ("reel.smoothing", False), ("reel.auto_hover", False),
                       ("reel.min_confidence", False), ("reel.lost_fish_timeout", False),
                       ("reel.min_switch_ms", False), ("reel.calm_zone", False),
                       ("reel.edge_margin", False), ("reel.max_hold_seconds", False)]),
    ("Casting", [("casting.mode", True), ("casting.pre_cast_delay", False), ("casting.hold_seconds", False),
                 ("casting.perfect_threshold", False), ("casting.jitter", False)]),
    ("Shake", [("shake.mode", True), ("shake.click_interval", False), ("shake.persistence_frames", False),
               ("shake.nav_toggle_key", False)]),
    ("Rod & hotbar", [("equipment.rod_slot_key", True), ("equipment.reequip_on_recovery", False),
                      ("equipment.equip_before_cast", False)]),
    ("Detection", [("detection.reel_mode", False), ("detection.fish_any_colour", False),
                   ("detection.shake_by_colour", False)]),
    ("Timing & recovery", [("timing.stuck_seconds", False), ("timing.bite_timeout", False), ("timing.post_catch_delay", False),
                           ("timing.max_consecutive_recoveries", False), ("timing.recovery_click", False)]),
]


# Plain wording for the fields everyone sees (the profile schema's own help stays for the advanced view).
PLAIN = {
    "reel.mode": ("Tracking mode", "Standard suits most rods. Precision plans ahead and helps rods with a very "
                                   "small bar; it learns for a few seconds first."),
    "casting.mode": ("Cast style", "Perfect waits for a full power bar. Timed holds for a set time. Quick is a short "
                             "cast right away."),
    "shake.mode": ("Shake", "Click finds and clicks the shake button. Navigation uses Roblox's UI navigation keys "
                            "instead."),
    "equipment.rod_slot_key": ("Rod hotbar key", "The key that equips your rod, used to get back to fishing after "
                                                 "something goes wrong."),
    "timing.post_catch_delay": ("Wait after a catch", "Pause before casting again. Lower recasts sooner; raise it "
                                                      "if a cast is sometimes ignored right after a catch."),
    "minigame.lead_ms": ("Click timing", "Clicks are sent this much before the pendulum reaches the spot, to cover "
                                         "your PC's delay. Raise it if clicks land late (on the red after the lit "
                                         "part); lower it if they land early."),
    "minigame.keep_reeling": ("Also follow the fish", "Steer the catch bar too while playing the rod minigame."),
}

# The few settings shown first, in this order; everything else is under "Show all settings".
BASIC = [SENSITIVITY, "casting.mode", "timing.post_catch_delay", "equipment.rod_slot_key"]
CHOICE_LABELS = {"casting.mode": {"perfect": "Perfect", "timed": "Timed", "normal": "Quick"}}


def _meta(path: str) -> dict:
    if path in PLAIN:
        label, help_text = PLAIN[path]
        section, name = path.split(".")
        meta = dict(dict(field_meta(type(getattr(Profile(), section)))).get(name, {}))
        meta.update(label=label, help=help_text)
        return meta
    if path == SENSITIVITY:
        return dict(label="Sensitivity", help="How hard the bar chases the fish. Lower is calmer: fewer, longer "
                                              "clicks. Raise it only if the bar is too slow to follow the fish.",
                    min=1, max=10, step=1, decimals=0, choices=None, kind="slider", suffix="", ends=["Calm", "Quick"])
    section, name = path.split(".")
    cls = type(getattr(Profile(), section))
    return dict(field_meta(cls)).get(name, {"label": name})


def get_value(profile: Profile, path: str) -> Any:
    if path == SENSITIVITY:
        return sensitivity(profile)
    section, name = path.split(".")
    return getattr(getattr(profile, section), name)


def set_value(profile: Profile, path: str, value: Any) -> Any:
    """Set a field from editor input, converted and checked against its limits. Returns the stored value."""
    if path == SENSITIVITY:
        set_sensitivity(profile, int(value))
        return sensitivity(profile)
    section, name = path.split(".")
    obj = getattr(profile, section)
    if not any(f.name == name for f in dc_fields(obj)):
        raise KeyError(path)
    old = getattr(obj, name)
    meta = _meta(path)
    if isinstance(old, bool):
        v: Any = bool(value)
    elif isinstance(old, int):
        v = int(round(float(value)))
    elif isinstance(old, float):
        v = float(value)
    else:
        v = str(value)
    if meta.get("choices") and v not in meta["choices"]:
        raise ValueError(f"{meta.get('label', path)}: choose one of {', '.join(meta['choices'])}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if meta.get("min") is not None:
            v = max(meta["min"], v)
        if meta.get("max") is not None:
            v = min(meta["max"], v)
    setattr(obj, name, v)
    return v


def _field(profile: Profile, path: str, simple: bool) -> dict:
    m = _meta(path)
    v = get_value(profile, path)
    kind = m.get("kind") or ("bool" if isinstance(v, bool) else "choice" if m.get("choices") else
                             "int" if isinstance(v, int) else "float" if isinstance(v, float) else "text")
    return {"path": path, "label": m.get("label", path), "help": m.get("help", ""), "kind": kind, "value": v,
            "choices": m.get("choices"), "min": m.get("min"), "max": m.get("max"), "step": m.get("step"),
            "suffix": m.get("suffix", ""), "simple": simple, "experimental": bool(m.get("experimental")),
            "choice_labels": CHOICE_LABELS.get(path), "ends": m.get("ends")}


def editor_schema(profile: Profile) -> dict:
    """Sections for the configuration editor of this profile's rod."""
    rod = definition(profile.equipment.rod_name if profile.equipment.rod_name != "Any rod" else "")
    b = behaviour_for(profile.minigame.kind)
    sections = []
    rod_basic = [f"minigame.{n}" for n in b.settings] if b.kind != "none" else []
    basic_paths = rod_basic + BASIC
    if b.kind != "none":
        mg = [(f"minigame.{n}", True) for n in b.settings] + [(f"minigame.{n}", False) for n in b.advanced]
        sections.append({"title": f"{b.label} minigame", "summary": b.summary,
                         "fields": [_field(profile, p, s) for p, s in mg]})
    for title, items in BASE_SECTIONS:
        sections.append({"title": title, "fields": [_field(profile, p, s) for p, s in items]})
    return {"rod": rod.name, "behaviour": b.label, "special": rod.special, "status": rod.status,
            "status_text": STATUS_TEXT.get(rod.status, rod.status), "note": rod.note,
            "basic": [_field(profile, p, True) for p in basic_paths],
            # "Show all settings": every field not already in the basics
            "sections": [dict(sec, fields=[f for f in sec["fields"] if f["path"] not in basic_paths])
                         for sec in sections if any(f["path"] not in basic_paths for f in sec["fields"])]}
