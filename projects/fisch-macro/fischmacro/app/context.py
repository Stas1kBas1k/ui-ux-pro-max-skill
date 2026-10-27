"""Application state shared by all pages: settings, profiles, engine, hotkeys."""
from __future__ import annotations

import logging
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

from fischmacro.automation.engine import AutomationEngine, Status
from fischmacro.diagnostics.logs import set_level
from fischmacro.diagnostics.stats import StatsStore
from fischmacro.input.hotkeys import HotkeyManager, reserved_conflicts
from fischmacro.profiles.manager import ProfileError, ProfileManager, SettingsStore
from fischmacro.profiles.schema import AppSettings, Profile

log = logging.getLogger(__name__)


class AppContext(QObject):
    hotkey = Signal(str)            # emitted on the GUI thread for every hotkey action
    profile_switched = Signal()
    profile_auto_changed = Signal(str, object)  # the engine changed the profile itself (auto-calibration)
    rod_detected = Signal(str)
    notice = Signal(str, str)                   # (title, message) for toasts from background decisions
    settings_changed = Signal()
    appearance_changed = Signal()   # theme / text size changed: the window is rebuilt

    def __init__(self, settings_store: SettingsStore | None = None, profiles: ProfileManager | None = None,
                 stats: StatsStore | None = None):
        super().__init__()
        self.settings_store = settings_store or SettingsStore()
        self.settings: AppSettings = self.settings_store.load()
        if not self.settings.routines:
            from fischmacro.automation.routines import preset_copies as routine_presets
            self.settings.routines = routine_presets()   # all disabled until you enable them
        if not self.settings.watchers:
            from fischmacro.automation.watchers import preset_copies as watcher_presets
            self.settings.watchers = watcher_presets()
        set_level(self.settings.logging.level)
        self.profiles = profiles or ProfileManager()
        self.profile: Profile = self._load_active()
        self.stats = stats or StatsStore()
        self.engine = AutomationEngine(self.settings, self.profile, self.stats)
        # Called on the vision thread; a queued signal moves the save to the GUI thread.
        self.engine.on_profile_changed = self.profile_auto_changed.emit
        self.engine.on_rod_detected = self.rod_detected.emit
        self.profile_auto_changed.connect(self._on_auto_changed)
        self.rod_detected.connect(self.handle_rod)
        self.hotkeys = HotkeyManager(self.settings.hotkeys.as_dict(), self._on_hotkey_thread)
        self.global_hotkeys = False
        self.activity: deque = deque(maxlen=300)  # recent engine events, shared across window rebuilds
        self.saved_capture_mode: str | None = None  # set when --simulation overrides the mode for one run
        self._profile_timer = QTimer(self)
        self._profile_timer.setSingleShot(True)
        self._profile_timer.setInterval(400)
        self._profile_timer.timeout.connect(self.save_profile)

    def _load_active(self) -> Profile:
        name = self.settings.active_profile
        try:
            return self.profiles.load(name)
        except ProfileError:
            first = self.profiles.names()[0]
            self.settings.active_profile = first
            return self.profiles.load(first)

    # ------------------------------------------------------------------ hotkeys
    def start_hotkeys(self) -> bool:
        self.global_hotkeys = self.hotkeys.start()
        return self.global_hotkeys

    def _on_hotkey_thread(self, action: str) -> None:
        # Runs on the listener thread. The emergency stop acts immediately here;
        # everything else is forwarded to the GUI thread.
        if action == "stop":
            self.engine.emergency_stop()
        self.hotkey.emit(action)

    def apply_hotkeys(self) -> list[str]:
        errors = self.hotkeys.set_bindings(self.settings.hotkeys.as_dict())
        self.save_settings()
        return errors

    def game_keys(self) -> dict[str, str]:
        p = self.profile
        keys = {"rod key": p.equipment.rod_slot_key}
        if p.shake.mode == "navigation":
            keys.update({"navigation toggle": p.shake.nav_toggle_key, "navigation confirm": p.shake.nav_confirm_key})
        for mid in ("timed_actions", "totem"):
            mod = p.modules.get(mid, {})
            if mod.get("enabled"):
                for k, v in mod.items():
                    if k.endswith("_key") and v:
                        keys[f"{mid} {k}"] = v
        return keys

    def hotkey_warnings(self) -> list[str]:
        return reserved_conflicts(self.settings.hotkeys.as_dict(), self.game_keys())

    # ------------------------------------------------------------------ persistence
    def use_simulation_for_this_run(self) -> None:
        self.saved_capture_mode = self.settings.capture.mode
        self.settings.capture.mode = "simulation"

    def save_settings(self) -> None:
        to_save = self.settings
        if self.saved_capture_mode is not None and self.settings.capture.mode == "simulation":
            import copy
            to_save = copy.deepcopy(self.settings)
            to_save.capture.mode = self.saved_capture_mode
        try:
            self.settings_store.save(to_save)
        except OSError as exc:
            log.error("Could not save settings: %s", exc)

    def profile_edited(self, *_):
        self._profile_timer.start()

    def save_profile(self) -> None:
        try:
            self.profiles.save(self.profile)
        except (OSError, ProfileError) as exc:
            log.error("Could not save profile: %s", exc)

    def switch_profile(self, name: str) -> None:
        if self.engine.status in (Status.RUNNING, Status.PAUSED):
            raise ProfileError("Stop automation before switching profiles.")
        self.save_profile()
        profile = self.profiles.load(name)
        self.engine.set_profile(profile)
        self.profile = profile
        self.settings.active_profile = name
        self.save_settings()
        self.profile_switched.emit()
        log.info("Active profile: %s", name)

    def reload_profile_object(self, profile: Profile) -> None:
        """Use a freshly loaded/renamed profile object as the active one."""
        if self.engine.status in (Status.RUNNING, Status.PAUSED):
            raise ProfileError("Stop automation first.")
        self.engine.set_profile(profile)
        self.profile = profile
        self.settings.active_profile = profile.name
        self.save_settings()
        self.profile_switched.emit()

    def settings_edited(self, field: str = "") -> None:
        set_level(self.settings.logging.level)
        self.save_settings()
        self.settings_changed.emit()

    def restart_vision_if_idle(self) -> bool:
        """Apply capture-source changes. Only possible while automation is not running."""
        if self.engine.status in (Status.RUNNING, Status.PAUSED):
            return False
        was = self.engine.status == Status.MONITORING
        self.engine.stop_vision()
        if was:
            self.engine.start_vision()
        return True

    # ------------------------------------------------------------------ automatic rod / skin profiles
    def _unique_name(self, base: str) -> str:
        from fischmacro.profiles.manager import _SAFE
        base = _SAFE.sub(" ", base).strip()[:50] or "Rod"
        name, i = base, 2
        while self.profiles.exists(name):
            name, i = f"{base} ({i})", i + 1
        return name

    def _profiles_for_rod(self, rod: str) -> list[Profile]:
        from fischmacro.vision.ocr import fuzzy_contains, normalize
        want = normalize(rod)
        out = []
        for name in self.profiles.names():
            try:
                p = self.profiles.load(name)
            except ProfileError:
                continue
            have = normalize(p.equipment.rod_name)
            if have and have != "any rod" and (have in want or want in have or fuzzy_contains(want, have)):
                out.append(p)
        return out

    def _use_profile(self, profile: Profile) -> None:
        self.profile = profile
        self.settings.active_profile = profile.name
        self.engine.request_profile(profile)
        self.save_settings()
        self.profile_switched.emit()

    def handle_rod(self, rod: str) -> None:
        """A rod watcher read a rod name: switch to its profile, creating one the first time."""
        if not self.settings.notifications.auto_profiles or not rod:
            return
        from fischmacro.vision.ocr import fuzzy_contains, normalize
        current = normalize(self.profile.equipment.rod_name)
        if current and current != "any rod" and fuzzy_contains(rod, current):
            return  # already on this rod
        matches = self._profiles_for_rod(rod)
        if matches:
            self._use_profile(matches[0])
            self.notice.emit("Rod profile", f"{rod} detected - using profile '{matches[0].name}'")
            return
        import copy

        from fischmacro.profiles.rod_presets import apply_preset, find_preset
        p = copy.deepcopy(self.profile)
        p.name = self._unique_name(rod)
        p.equipment.rod_name = rod
        p.equipment.skin = ""
        preset = find_preset(rod)
        if preset:
            apply_preset(p, preset)
        self.profiles.save(p)
        self._use_profile(p)
        self.notice.emit("New rod profile", f"Created '{p.name}'" + (f" with the {preset.name} preset" if preset else "")
                         + " - colours adapt automatically on the first catch.")

    def _on_auto_changed(self, reason: str, info) -> None:
        """Auto-calibration changed the profile. A new skin on a calibrated rod becomes its own profile."""
        from fischmacro.profiles.schema import DetectionConfig
        defaults = DetectionConfig()
        info = info or {}
        calibrated_before = info.get("old_bar") not in (None, defaults.bar_color)
        if reason != "adapt" or not self.settings.notifications.auto_profiles or not calibrated_before:
            self.profile_edited()
            return
        # Another saved profile of this rod already has these colours: switch to it, keep both files as they are.
        for other in self._profiles_for_rod(self.profile.equipment.rod_name):
            if other.name != self.profile.name and other.detection.bar_color == info.get("new_bar") \
                    and other.detection.fish_color == info.get("new_fish"):
                self._use_profile(other)
                self.notice.emit("Skin profile", f"Recognised skin - using '{other.name}'")
                return
        # Otherwise the in-memory profile (now holding the new colours) is saved under a new skin name;
        # the original file on disk keeps the old skin's colours.
        n = len(self._profiles_for_rod(self.profile.equipment.rod_name)) + 1
        base = self.profile.equipment.rod_name if self.profile.equipment.rod_name != "Any rod" else self.profile.name
        self.profile.name = self._unique_name(f"{base} (skin {n})")
        self.profile.equipment.skin = f"skin {n}"
        self.profiles.save(self.profile)
        self.settings.active_profile = self.profile.name
        self.save_settings()
        self.profile_switched.emit()
        self.notice.emit("New skin profile", f"Saved '{self.profile.name}' for the new rod skin")

    def shutdown(self) -> None:
        self.hotkeys.stop()
        self.engine.shutdown()
        self._profile_timer.stop()
        self.save_profile()
        self.save_settings()
        self.stats.close()
