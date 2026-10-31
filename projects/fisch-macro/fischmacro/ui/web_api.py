"""Everything the HTML interface can ask for or do, as plain Python (testable without a window).

The web page calls ``WebApi.call(method, args)``; every visible button maps to one method here, and every
method works on the same ``AppContext`` and engine as the classic interface. Results are JSON-able dicts.
"""
from __future__ import annotations

import base64
import copy
import dataclasses
import time
from typing import Any, Callable

import cv2

from fischmacro import APP_NAME, __version__, licensing
from fischmacro.automation.engine import Status
from fischmacro.profiles.library import DEFAULT_SKIN, RodLibrary, is_dirty
from fischmacro.profiles.manager import ProfileError
from fischmacro.profiles.schema import field_meta, to_dict
from fischmacro.rods import behaviour_for
from fischmacro.rods.config import definition, editor_schema, get_value, set_value
from fischmacro.ui.rod_art import rod_hue

STEP_NAMES = {"IDLE": "Idle", "CASTING": "Casting", "WAITING_FOR_BITE": "Waiting for a bite", "SHAKE": "Shaking",
              "REELING": "Reeling", "CATCH_CONFIRMED": "Caught - next cast", "RECOVERY": "Recovering",
              "ERROR": "Stopped on an error"}

# App settings shown on the Settings page: (section title, [(settings attribute, field)])
SETTINGS_SECTIONS = [
    ("Game window", [("capture", "mode"), ("capture", "window_title"), ("capture", "require_focus")]),
    ("While fishing", [("mini", "shrink_on_start"), ("mini", "always_on_top"), ("input", "observe_only")]),
    ("Input", [("input", "method"), ("input", "click_hold_ms"), ("input", "key_hold_ms")]),
    ("Notifications", [("notifications", "toasts"), ("notifications", "tray_icon"),
                       ("notifications", "desktop_notifications"), ("notifications", "sound_on_error")]),
    ("Startup", [("startup", "start_minimized"), ("startup", "confirm_exit_while_running"),
                 ("appearance", "interface")]),
]

# Wording for settings whose schema has no label, or whose help is written for the classic pages.
SETTINGS_TEXT = {
    "capture.mode": ("Capture source", "Window follows the Roblox window. Monitor captures a whole screen. "
                                       "Simulation is the built-in test game and sends nothing to Roblox."),
    "mini.shrink_on_start": ("Small window while fishing", "The app turns into a small status card when fishing "
                                                           "starts, so it does not cover the game."),
    "mini.always_on_top": ("Keep the small window on top", ""),
}


class ApiError(Exception):
    pass


class WebApi:
    def __init__(self, ctx, window=None):
        self.ctx = ctx
        self.window = window          # the Qt main window, for native tools (region picker, wizard, panels)
        self.lib = RodLibrary(ctx.profiles, ctx.settings.library)
        self.draft = None             # profile being edited in the Rod Library or the editor
        self.saved = None
        self.draft_rod = ""
        self.draft_skin = DEFAULT_SKIN
        self.test_result = ""
        self._methods: dict[str, Callable] = {
            name[4:].replace("__", "."): getattr(self, name) for name in dir(self) if name.startswith("api_")}

    # ------------------------------------------------------------------ dispatch
    def call(self, method: str, args: dict | None = None) -> Any:
        fn = self._methods.get(method)
        if fn is None:
            raise ApiError(f"unknown method {method}")
        return fn(**(args or {}))

    # ------------------------------------------------------------------ state (polled ~5x a second)
    def api_state(self) -> dict:
        eng, ctx = self.ctx.engine, self.ctx
        s = eng.snapshot()
        p = ctx.profile
        obs = s.observation
        tr = eng.fsm.tracker.state
        running = s.status in (Status.RUNNING, Status.PAUSED)
        if s.simulated:
            game = ("test", "Test game", "Simulation - no real input")
        elif s.status == Status.STOPPED:
            game = ("idle", "Not checked", "Looked for when you press Start")
        elif s.window_found:
            game = ("ok", "Roblox found", "Focused" if s.window_focused else "Click into Roblox to fish") \
                if s.window_focused else ("warn", "Roblox found", "Click into Roblox to fish")
        else:
            game = ("bad", "Roblox not found", "Open Roblox and join Fisch")
        cal = eng.autocal_status
        if eng.autocalibrating:
            calib = ("busy", "Calibrating", cal)
        elif cal.startswith("Calibrated"):
            calib = ("ok", "Calibrated", cal)
        elif "fail" in cal.lower() or "timed out" in cal.lower():
            calib = ("warn", "Not calibrated", cal)
        else:
            calib = ("ok", "Built-in", "Works without calibration on most setups")
        if running and s.fsm_state == "REELING" and tr.usable:
            track = ("ok" if tr.confidence > 0.6 else "warn", f"{tr.confidence:.0%} sure",
                     f"Fish moving {tr.direction}", tr.confidence)
        elif obs is not None and s.status != Status.STOPPED and obs.reel.ui_present:
            track = ("ok", "Reel seen", "Fish " + ("found" if obs.reel.fish_found else "not found"), 0.5)
        else:
            track = ("idle", "Waiting", "Starts when the reel appears", 0.0)
        sess = s.session
        rod = p.equipment.rod_name if p.equipment.rod_name and p.equipment.rod_name != "Any rod" else \
            ("Automatic" if ctx.settings.rod_detect.enabled else "Any rod")
        b = behaviour_for(p.minigame.kind)
        return {
            "status": s.status.value, "running": running, "paused": s.status == Status.PAUSED,
            "step": STEP_NAMES.get(s.fsm_state, s.fsm_state.title()) if running else s.status.value,
            "message": s.message or "", "error": s.last_error or "",
            "game": dict(zip(("tone", "value", "detail"), game)),
            "rod": {"name": rod, "skin": p.equipment.skin or DEFAULT_SKIN, "behaviour": b.label,
                    "special": p.minigame.kind != "none", "hue": rod_hue(rod, p.minigame.kind)},
            "profile": p.name, "calibration": dict(zip(("tone", "value", "detail"), calib)),
            "tracking": dict(zip(("tone", "value", "detail", "level"), track)),
            "session": {"caught": sess.catches, "escaped": sess.failures,
                        "per_hour": round(sess.catches_per_hour) if sess.catches_per_hour else 0,
                        "time": _hms(sess.active_seconds)},
            "simulated": s.simulated, "observe_only": ctx.settings.input.observe_only,
            "hotkeys": {k: v.upper() for k, v in ctx.settings.hotkeys.as_dict().items()},
            "start_report": [{"stage": n, "ok": ok, "detail": d} for n, ok, d in eng.start_report],
            "calibrating": eng.autocalibrating, "test_result": self.test_result,
            "licence": licensing.current().state,
        }

    # ------------------------------------------------------------------ automation
    def api_start(self) -> dict:
        if self.window is not None and hasattr(self.window, "start_automation"):
            self.window.start_automation()
        else:
            self.ctx.save_profile()
            self.ctx.engine.start_automation()
        return self.api_state()

    def api_stop(self) -> dict:
        self.ctx.engine.emergency_stop()
        self.ctx.engine.inputs.enable()  # the emergency stop's lock is lifted for the next Start
        return self.api_state()

    def api_pause(self) -> dict:
        self.ctx.engine.toggle_pause()
        return self.api_state()

    def api_watch(self) -> dict:
        if self.ctx.engine.status == Status.STOPPED:
            self.ctx.engine.start_vision()
        return self.api_state()

    # ------------------------------------------------------------------ rod library
    def api_rods(self, query: str = "", category: str = "All") -> dict:
        self.lib.refresh()
        out = []
        active_rod = self.ctx.profile.equipment.rod_name
        for r in self.lib.search(query, category):
            info = self.lib.info(r)
            d = definition(r)
            out.append({"name": r, "kind": info.kind, "special": info.special,
                        "behaviour": d.label if info.special else ("Tuned settings" if info.preset_note else
                                                                    "Standard reel"),
                        "configured": bool(info.profiles), "favourite": info.favourite,
                        "active": r == active_rod, "hue": rod_hue(r, info.kind),
                        "tuned": bool(info.preset_note)})
        from fischmacro.game_data import ALL_RODS
        return {"rods": out, "count": len(out), "total": len(ALL_RODS), "categories": ["All", "Special minigame", "Favourites",
                                                                 "Recent", "Configured"]}

    def api_rod__favourite(self, rod: str) -> dict:
        on = self.lib.toggle_favourite(rod)
        self.ctx.save_settings()
        return {"favourite": on}

    def api_rod__open(self, rod: str, skin: str = DEFAULT_SKIN) -> dict:
        self.draft, created = self.lib.load_or_create(rod, skin, self.ctx.profile)
        self.saved = None if created else copy.deepcopy(self.draft)
        self.draft_rod, self.draft_skin = rod, skin
        return self._draft_view()

    def api_rod__add_skin(self, rod: str, skin: str) -> dict:
        skin = skin.strip()
        if not skin:
            raise ApiError("Give the skin a name")
        self.lib.add_skin(rod, skin)
        self.ctx.save_settings()
        return self.api_rod__open(rod, skin)

    def api_draft__set(self, path: str, value: Any) -> dict:
        if self.draft is None:
            raise ApiError("Open a rod or profile first")
        set_value(self.draft, path, value)
        return self._draft_view()

    def api_draft__reset(self) -> dict:
        if self.draft is None:
            raise ApiError("Open a rod or profile first")
        name = self.draft.name
        rod = self.draft.equipment.rod_name or "Any rod"
        fresh = self.lib.recommended(rod, self.draft.equipment.skin or DEFAULT_SKIN, self.draft)
        fresh.name, fresh.regions, fresh.notes = name, self.draft.regions, self.draft.notes
        fresh.equipment.rod_name = self.draft.equipment.rod_name
        self.draft = fresh
        return self._draft_view()

    def api_draft__revert(self) -> dict:
        if self.saved is not None:
            self.draft = copy.deepcopy(self.saved)
        return self._draft_view()

    def api_draft__save(self, use: bool = True) -> dict:
        if self.draft is None:
            raise ApiError("Nothing to save")
        if use and self.ctx.engine.status in (Status.RUNNING, Status.PAUSED) and \
                self.draft.name != self.ctx.profile.name:
            raise ApiError("Stop fishing before switching to another rod")
        self.lib.save(self.draft)
        self.saved = copy.deepcopy(self.draft)
        if use:
            if self.draft_rod:
                self.lib.mark_used(self.draft_rod)
                self.ctx.settings.rod_detect.enabled = False
            self.ctx._use_profile(copy.deepcopy(self.draft))
            self.ctx.save_settings()
        elif self.draft.name == self.ctx.profile.name:
            self.ctx.reload_profile_object(copy.deepcopy(self.draft))
        return self._draft_view()

    def _draft_view(self) -> dict:
        d = self.draft
        rod = self.draft_rod or d.equipment.rod_name
        return {"profile": d.name, "rod": rod, "skin": self.draft_skin if self.draft_rod else
                (d.equipment.skin or DEFAULT_SKIN), "skins": self.lib.skins_for(rod) if rod else [DEFAULT_SKIN],
                "saved": self.saved is not None, "dirty": is_dirty(d, self.saved),
                "in_use": d.name == self.ctx.profile.name, "schema": editor_schema(d),
                "hue": rod_hue(rod, d.minigame.kind)}

    # ------------------------------------------------------------------ profiles
    def api_profiles(self) -> dict:
        out = []
        for n in self.ctx.profiles.names():
            try:
                p = self.ctx.profile if n == self.ctx.profile.name else self.ctx.profiles.load(n)
            except ProfileError:
                continue
            rod = p.equipment.rod_name or "Any rod"
            out.append({"name": n, "rod": rod, "skin": p.equipment.skin, "in_use": n == self.ctx.profile.name,
                        "behaviour": behaviour_for(p.minigame.kind).label, "hue": rod_hue(rod, p.minigame.kind)})
        return {"profiles": out, "active": self.ctx.profile.name}

    def api_profile__open(self, name: str) -> dict:
        p = self.ctx.profile if name == self.ctx.profile.name else self.ctx.profiles.load(name)
        self.draft, self.saved = copy.deepcopy(p), copy.deepcopy(p)
        self.draft_rod, self.draft_skin = "", p.equipment.skin or DEFAULT_SKIN
        return self._draft_view()

    def api_profile__use(self, name: str) -> dict:
        try:
            self.ctx.switch_profile(name)
        except ProfileError as exc:
            raise ApiError(str(exc)) from exc
        return self.api_profiles()

    def api_profile__duplicate(self, name: str, new: str) -> dict:
        try:
            self.ctx.save_profile()
            self.ctx.profiles.duplicate(name, new.strip())
        except ProfileError as exc:
            raise ApiError(str(exc)) from exc
        return self.api_profiles()

    def api_profile__rename(self, name: str, new: str) -> dict:
        try:
            if name == self.ctx.profile.name:
                self.ctx.save_profile()
                self.ctx.reload_profile_object(self.ctx.profiles.rename(name, new.strip()))
            else:
                self.ctx.profiles.rename(name, new.strip())
        except ProfileError as exc:
            raise ApiError(str(exc)) from exc
        return self.api_profiles()

    def api_profile__delete(self, name: str) -> dict:
        if name == self.ctx.profile.name:
            raise ApiError("This profile is in use - switch to another one first")
        try:
            self.ctx.profiles.delete(name)
        except ProfileError as exc:
            raise ApiError(str(exc)) from exc
        return self.api_profiles()

    def api_profile__export(self, name: str) -> dict:
        path = self._native("save_file", f"{name}.json")
        if not path:
            return {"cancelled": True}
        self.ctx.save_profile()
        self.ctx.profiles.export(name, path)
        return {"path": str(path)}

    def api_profile__import(self) -> dict:
        path = self._native("open_file")
        if not path:
            return {"cancelled": True}
        try:
            p = self.ctx.profiles.import_file(path)
        except ProfileError as exc:
            raise ApiError(str(exc)) from exc
        return {"imported": p.name, **self.api_profiles()}

    # ------------------------------------------------------------------ calibration and checks
    def api_calibrate(self) -> dict:
        eng = self.ctx.engine
        if eng.autocalibrating:
            eng.cancel_autocalibration()
        else:
            eng.start_autocalibration()
        return self.api_state()

    def api_calibrate__manual(self) -> dict:
        self._native("regions")
        return {"ok": True}

    def api_test_minigame(self) -> dict:
        import threading
        profile = copy.deepcopy(self.ctx.profile)
        self.test_result = "Running 3 catches in the test game..."

        def work():
            from fischmacro.simulation.game import SimulatedFischGame
            from fischmacro.simulation.harness import run_simulation
            try:
                p = profile
                p.regions = type(p)().regions
                p.detection = type(p.detection)()
                kind = p.minigame.kind
                g = SimulatedFischGame(seed=7, difficulty=0.4)
                if kind in ("lullaby", "migu", "halibut", "targets"):
                    g.rod_minigame = kind
                    g.mini_action = p.minigame.migu_key if kind == "migu" else (p.minigame.action or "click")
                if kind in ("stellarwave",):
                    p.minigame.kind = "none"  # the test game has no zodiac strip; the reel itself is tested
                res = run_simulation(p, game=g, cycles=3, max_time=240, fps=40)
                msg = f"{res.outcomes.get('success', 0)}/3 caught in the test game"
                if g.rod_minigame:
                    msg += f" - rod minigame {g.stats.mini_hits} hit, {g.stats.mini_misses} missed"
            except Exception as exc:  # noqa: BLE001
                msg = f"The test could not run: {exc}"
            self.test_result = msg
        threading.Thread(target=work, name="minigame-test", daemon=True).start()
        return {"started": True}

    def api_wizard(self) -> dict:
        self._native("wizard")
        return {"ok": True}

    def api_open_panel(self, name: str) -> dict:
        """Tools kept from the classic interface (add-ons, hunts, assistant, vision, logs), in their own window."""
        self._native("panel", name)
        return {"ok": True}

    # ------------------------------------------------------------------ settings
    def api_settings(self) -> dict:
        st = self.ctx.settings
        sections = []
        for title, items in SETTINGS_SECTIONS:
            fields = []
            for sec, name in items:
                obj = getattr(st, sec)
                meta = dict(dict(field_meta(type(obj))).get(name, {"label": name}))
                if f"{sec}.{name}" in SETTINGS_TEXT:
                    meta["label"], meta["help"] = SETTINGS_TEXT[f"{sec}.{name}"]
                v = getattr(obj, name)
                kind = meta.get("kind") or ("bool" if isinstance(v, bool) else "choice" if meta.get("choices") else
                                            "int" if isinstance(v, int) else "float" if isinstance(v, float) else "text")
                fields.append({"path": f"{sec}.{name}", "label": meta.get("label", name), "help": meta.get("help", ""),
                               "kind": kind, "value": v, "choices": meta.get("choices"), "min": meta.get("min"),
                               "max": meta.get("max"), "suffix": meta.get("suffix", ""), "simple": True})
            sections.append({"title": title, "fields": fields})
        return {"sections": sections, "hotkeys": st.hotkeys.as_dict(), "hotkey_warnings": self.ctx.hotkey_warnings()}

    def api_settings__set(self, path: str, value: Any) -> dict:
        sec, name = path.split(".")
        if sec not in {s for _, items in SETTINGS_SECTIONS for s, _ in items}:
            raise ApiError(f"unknown setting {path}")
        obj = getattr(self.ctx.settings, sec)
        old = getattr(obj, name)
        meta = dict(field_meta(type(obj))).get(name, {})
        v = bool(value) if isinstance(old, bool) else int(value) if isinstance(old, int) else \
            float(value) if isinstance(old, float) else str(value)
        if meta.get("choices") and v not in meta["choices"]:
            raise ApiError(f"choose one of {', '.join(meta['choices'])}")
        setattr(obj, name, v)
        self.ctx.settings_edited(sec)
        if sec == "capture":
            self.ctx.restart_vision_if_idle()
        if sec == "appearance":
            self.ctx.appearance_changed.emit()  # the window is rebuilt with the chosen interface
        return self.api_settings()

    def api_hotkey__set(self, action: str, key: str) -> dict:
        from fischmacro.input.hotkeys import normalize_combo
        hk = self.ctx.settings.hotkeys
        if action not in hk.as_dict():
            raise ApiError(f"unknown action {action}")
        try:
            setattr(hk, action, normalize_combo(key))
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        self.ctx.apply_hotkeys()
        self.ctx.save_settings()
        return self.api_settings()

    # ------------------------------------------------------------------ diagnostics
    def api_diagnostics(self, image: bool = True) -> dict:
        eng = self.ctx.engine
        eng.set_preview(True)
        snap = eng.snapshot()
        tr = eng.fsm.tracker.state
        back = eng.inputs.backend
        recent = [{"ago": round(time.time() - t, 1), "what": w, "sent": sent, "error": err}
                  for t, w, sent, err in list(getattr(back, "recent", []))[-12:][::-1]]
        out = {"state": STEP_NAMES.get(snap.fsm_state, snap.fsm_state), "status": snap.status.value,
               "fps": round(snap.fps), "vision_ms": round(snap.process_ms, 1),
               "tracking": {"usable": tr.usable, "fish": round(tr.fish_x, 3), "speed": round(tr.fish_v, 2),
                            "direction": tr.direction, "confidence": round(tr.confidence, 2),
                            "ignored": tr.rejected, "coasting": tr.coasting},
               "inputs": recent, "minigame_log": list(eng.fsm.minigame.log)[-8:],
               "transitions": [{"ago": round(time.monotonic() - t, 1), "from": a.value, "to": b.value, "why": w}
                               for t, a, b, w in eng.fsm.history[-8:][::-1]],
               "error": snap.last_error, "image": None}
        if image and snap.preview is not None and snap.preview_obs is not None:
            from fischmacro.diagnostics.replay import draw
            img = draw(snap.preview.image, eng.profile, snap.preview_obs, eng.fsm,
                       [r["what"] for r in recent[:4] if not r["what"].startswith("move")], snap.preview.timestamp)
            h, w = img.shape[:2]
            if w > 1280:
                img = cv2.resize(img, (1280, int(h * 1280 / w)))
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                out["image"] = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
        return out

    def api_diagnostics__stop(self) -> dict:
        self.ctx.engine.set_preview(False)
        return {"ok": True}

    # ------------------------------------------------------------------ licence / about
    def api_licence(self) -> dict:
        s = licensing.current()
        return {"state": s.state, "message": s.message, "device_id": s.device_id, "key_hint": s.key_hint,
                "expires": s.expires}

    def api_licence__activate(self, key: str) -> dict:
        s = licensing.provider().activate(key.strip())
        return {"state": s.state, "message": s.message, "device_id": s.device_id}

    def api_about(self) -> dict:
        from fischmacro import paths
        return {"name": APP_NAME, "version": __version__, "data_dir": str(paths.data_dir())}

    # ------------------------------------------------------------------ helpers
    def _native(self, what: str, arg: Any = None):
        w = self.window
        if w is None or not hasattr(w, "native_action"):
            return None
        return w.native_action(what, arg)


def _hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def json_safe(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return to_dict(obj)
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    if hasattr(obj, "item"):  # numpy scalars
        return obj.item()
    return obj
