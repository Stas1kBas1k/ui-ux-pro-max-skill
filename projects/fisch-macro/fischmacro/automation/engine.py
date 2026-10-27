"""Runtime: capture thread -> bounded queue -> processing thread (vision + FSM).

The engine has no Qt dependency. The UI polls :meth:`AutomationEngine.snapshot`
and drains :meth:`AutomationEngine.drain_events` on a timer, so worker threads
never touch widgets.
"""
from __future__ import annotations

import copy
import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from fischmacro.automation.fsm import FishingStateMachine, State
from fischmacro.automation.reel_controller import ReelDebug
from fischmacro.diagnostics.stats import SessionStats, StatsStore
from fischmacro.input.controller import InputController, create_backend
from fischmacro.profiles.schema import AppSettings, Profile, Routine, Watcher
from fischmacro.automation.minigame_solvers import MinigameSolver
from fischmacro.automation.modules import ModuleHost
from fischmacro.automation.reel_controller import ReelController
from fischmacro.automation.routines import RoutineContext, RoutineRunner, RoutineScheduler
from fischmacro.automation.addons import AddonsService
from fischmacro.game_data import LULLABY_MODES
from fischmacro.automation.watchers import WatcherService
from fischmacro.diagnostics.notify import DiscordNotifier
from fischmacro.vision.autocal import AutoCalibrator, AutoCalResult, apply_result
from fischmacro.vision.capture import CaptureError, CaptureSource, ScreenCapture, SimulationCapture
from fischmacro.vision.engine import Observation, VisionEngine
from fischmacro.vision.frame import Frame, union_rect

log = logging.getLogger(__name__)


class Status(str, Enum):
    STOPPED = "Stopped"          # no capture
    MONITORING = "Monitoring"    # capture + vision, no input
    RUNNING = "Running"
    PAUSED = "Paused"


@dataclass
class EngineSnapshot:
    status: Status = Status.STOPPED
    fsm_state: str = "IDLE"
    game_state: str = "No capture"
    message: str = ""
    last_error: str = ""
    observation: Observation | None = None
    reel: ReelDebug = field(default_factory=ReelDebug)
    preview: Frame | None = None
    preview_obs: Observation | None = None
    fps: float = 0.0
    capture_ms: float = 0.0
    process_ms: float = 0.0
    window_found: bool = False
    window_focused: bool = False
    simulated: bool = False
    held_inputs: tuple = ()
    session: SessionStats = field(default_factory=SessionStats)
    frame_id: int = 0


@dataclass
class _CaptureFailure:
    message: str
    window_missing: bool
    timestamp: float


class AutomationEngine:
    def __init__(self, settings: AppSettings, profile: Profile, stats: StatsStore | None = None,
                 source: CaptureSource | None = None, inputs: InputController | None = None):
        self.settings = settings
        self.profile = profile
        self.stats_store = stats
        self._source_override = source
        self._inputs_override = inputs
        self.source: CaptureSource | None = None
        self.sim_game = None
        self.inputs: InputController = inputs or InputController()
        self.vision = VisionEngine(profile)
        self._abort = threading.Event()
        self.fsm = self._new_fsm()
        self._lock = threading.RLock()
        self._queue: queue.Queue = queue.Queue(maxsize=2)
        self._stop_threads = threading.Event()
        self._threads: list[threading.Thread] = []
        self._events: deque[tuple[float, str, str]] = deque(maxlen=500)
        self._snap = EngineSnapshot()
        self._status = Status.STOPPED
        self._preview_wanted = False
        self._last_full = 0.0
        self._last_preview = 0.0
        self._focus_paused = False
        self._window_missing_since: float | None = None
        self._capture_failures = 0
        self._last_active_tick: float | None = None
        self.session = SessionStats()
        self.autocal = AutoCalibrator()
        self.autocal_status = ""
        self.autocal_result: AutoCalResult | None = None
        self._autocal_wizard_until = 0.0
        self._last_autocal_try = -1e9
        self._last_shake_seen = 0.0
        self._fish_missing_since: float | None = None
        self.on_profile_changed = None  # callback(reason) - the UI saves the profile
        self.scheduler = RoutineScheduler()
        self.routine_running = ""
        self.notifier = DiscordNotifier(lambda: self.settings.notifications)
        self._latest_image = None
        self.addons = AddonsService(self.settings.addons)
        self._lullaby_mode_set = ""
        self.watchers = WatcherService(self.active_watchers, lambda: self._latest_image,
                                       self._on_watch_match, self._on_rod_detected, on_text=self._on_watch_text)
        self.on_rod_detected = None    # callback(rod_name) - the UI decides which profile to use
        self.detected_rod = ""
        self._pending_profile: Profile | None = None

    # ------------------------------------------------------------------ setup
    def _new_fsm(self) -> FishingStateMachine:
        fsm = FishingStateMachine(self.profile, self.inputs, emit=self._on_event,
                                  sleep=lambda s: self._abort.wait(s),
                                  min_switch_interval=self.settings.input.min_switch_interval_ms / 1000.0)
        fsm.safe_point_hooks.append(self._routines_safe_point)
        return fsm

    def _make_source(self) -> CaptureSource:
        if self._source_override is not None:
            return self._source_override
        cap = self.settings.capture
        if cap.mode == "simulation":
            from fischmacro.simulation.game import SimulatedFischGame
            self.sim_game = SimulatedFischGame(1280, 720, difficulty=0.4)
            return SimulationCapture(self.sim_game)
        self.sim_game = None
        return ScreenCapture(cap.mode, cap.window_title, cap.monitor)

    def _make_inputs(self) -> InputController:
        if self._inputs_override is not None:
            return self._inputs_override
        i = self.settings.input
        backend = create_backend(self.sim_game, prefer_scancodes=not i.method.startswith("pynput"))
        return InputController(backend, i.click_hold_ms, i.key_hold_ms, i.mouse_nudge)

    @property
    def simulated(self) -> bool:
        return bool(self.source is not None and self.source.simulated)

    @property
    def status(self) -> Status:
        return self._status

    def set_profile(self, profile: Profile) -> None:
        with self._lock:
            if self._status in (Status.RUNNING, Status.PAUSED):
                raise RuntimeError("Stop automation before switching profiles")
            self.profile = profile
            self.vision = VisionEngine(profile)
            self.fsm = self._new_fsm()

    def set_preview(self, wanted: bool) -> None:
        self._preview_wanted = wanted

    # ------------------------------------------------------------------ lifecycle
    def start_vision(self) -> None:
        with self._lock:
            if self._threads:
                return
            self.source = self._make_source()
            self.inputs.release_all()
            self.inputs = self._make_inputs()
            self.fsm = self._new_fsm()
            self._stop_threads.clear()
            self._queue = queue.Queue(maxsize=2)
            self._threads = [
                threading.Thread(target=self._capture_loop, name="capture", daemon=True),
                threading.Thread(target=self._process_loop, name="vision", daemon=True),
            ]
            for t in self._threads:
                t.start()
            self._status = Status.MONITORING
            self.watchers.start()
            log.info("Vision started (%s)", "simulation" if self.simulated else self.settings.capture.mode)

    def stop_vision(self) -> None:
        self.stop_automation("vision stopped")
        self.watchers.stop()
        self._stop_threads.set()
        for t in self._threads:
            t.join(timeout=2.0)
        alive = [t.name for t in self._threads if t.is_alive()]
        if alive:
            log.warning("Threads did not stop in time: %s", alive)
        self._threads = []
        if self.source is not None:
            self.source.close()
        self._status = Status.STOPPED
        self.inputs.release_all()

    def start_automation(self) -> bool:
        if self._status in (Status.RUNNING, Status.PAUSED):
            return False
        self.start_vision()
        with self._lock:
            self._abort.clear()
            self.inputs.enable()
            self.session = SessionStats(profile=self.profile.name, started=time.time())
            if self.stats_store:
                self.session.session_id = self.stats_store.start_session(self.profile.name, self.simulated)
            self._focus_paused = False
            self._capture_failures = 0
            self._window_missing_since = None
            self._last_active_tick = None
            self._snap.last_error = ""
            self.vision.reset_background()
            self.scheduler.reset(time.monotonic(), 0)
            self.addons.reset(time.monotonic())
            self._lullaby_mode_set = ""
            self.fsm.start(time.monotonic())
            self._status = Status.RUNNING
        if not self.simulated and self.source is not None:
            self._focus_game()
        self._event("info", f"Automation started with profile '{self.profile.name}'"
                    + (" [SIMULATION - no real input]" if self.simulated else ""))
        return True

    def _focus_game(self) -> None:
        """Pressing Start in this window leaves Roblox in the background; bring it forward once."""
        try:
            win = self.source.locate()
            if not win.found:
                self._event("warning", f"Roblox window '{self.settings.capture.window_title}' not found - open the game first")
                return
            if not win.focused:
                from fischmacro.vision.win32 import focus_window
                if not focus_window(win.handle):
                    self._event("info", "Click the Roblox window once - fishing starts when it is focused")
        except Exception:  # noqa: BLE001 - focusing is a convenience only
            log.debug("Could not focus the game", exc_info=True)

    def stop_automation(self, reason: str = "stopped by user") -> None:
        # Release first, without waiting for the processing thread.
        self._abort.set()
        self.inputs.release_all()
        with self._lock:
            was_active = self._status in (Status.RUNNING, Status.PAUSED)
            self.fsm.stop(time.monotonic(), reason)
            self.inputs.release_all()
            if was_active:
                self._status = Status.MONITORING if self._threads else Status.STOPPED
                self._finish_session(reason)
        if was_active:
            self._event("info", f"Automation stopped: {reason}")

    def emergency_stop(self) -> None:
        """Hard stop: kill switch on input, release everything, stop the FSM."""
        self.inputs.disable()
        self.stop_automation("emergency stop")
        self._event("warning", "EMERGENCY STOP - all inputs released")

    def pause(self) -> None:
        with self._lock:
            if self._status != Status.RUNNING:
                return
            self._abort.set()
            self.inputs.release_all()
            self.fsm.running = False
            self._status = Status.PAUSED
        self._event("info", "Paused - all inputs released")

    def resume(self) -> None:
        with self._lock:
            if self._status != Status.PAUSED:
                return
            self._abort.clear()
            self.inputs.enable()
            self.vision.reset_background()
            self.fsm.resync(time.monotonic(), "resume")
            self._status = Status.RUNNING
            self._last_active_tick = None
        self._event("info", "Resumed")

    def toggle_pause(self) -> None:
        if self._status == Status.RUNNING:
            self.pause()
        elif self._status == Status.PAUSED:
            self.resume()

    def shutdown(self) -> None:
        self.inputs.disable()
        self.stop_vision()
        self.inputs.release_all()

    def _finish_session(self, reason: str) -> None:
        if self.stats_store and self.session.session_id is not None:
            self.stats_store.end_session(self.session, reason)

    # ------------------------------------------------------------------ events
    def _event(self, kind: str, message: str) -> None:
        level = logging.WARNING if kind in ("warning", "recovery", "disconnect") else \
            logging.ERROR if kind == "error" else logging.INFO
        log.log(level, message, extra={"kind": kind})
        self._events.append((time.time(), kind, message))
        if kind in ("error", "disconnect") and self.settings.notifications.discord_errors:
            self.notifier.send("Fisch Macro stopped" if kind == "error" else "Disconnected", message,
                               image=self._latest_image, key=kind, min_gap=30, error=True)
        if self.stats_store and kind in ("error", "recovery", "disconnect", "warning", "detection_error", "info", "reminder",
                                               "watcher", "rod", "autocal"):
            try:
                self.stats_store.add_event(self.session.session_id, kind, message)
            except Exception:  # noqa: BLE001
                log.exception("Could not store event")

    def _on_event(self, kind: str, message: str, **data) -> None:
        s = self.session
        if kind == "cycle":
            outcome = data.get("outcome")
            if outcome == "success":
                s.catches += 1
            elif outcome == "failure":
                s.failures += 1
            else:
                s.unconfirmed += 1
            s.durations.append(float(data.get("duration", 0.0)))
            every = self.settings.notifications.notify_every_catches
            if outcome == "success" and every and s.catches % every == 0:
                self.notifier.send("Catch milestone", f"{s.catches} catches this session ({self.profile.name})",
                                   key=f"milestone{s.catches}", min_gap=0)
            s.history.append((str(outcome), float(data.get("duration", 0.0))))
            if self.stats_store:
                self.stats_store.add_cycle(s.session_id, outcome, data.get("duration", 0.0), data.get("progress"),
                                           data.get("perfect_cast"), data.get("shake_clicks", 0))
        elif kind == "cast":
            s.casts += 1
            if data.get("perfect"):
                s.perfect_casts += 1
        elif kind == "recovery":
            s.recoveries += 1
        if kind == "routine":
            self._event("info", message)
            return
        if kind in ("state", "shake"):
            log.debug(message)
            if kind == "state":
                self._events.append((time.time(), kind, message))
            return
        self._event(kind, message)

    def drain_events(self) -> list[tuple[float, str, str]]:
        out = []
        while self._events:
            out.append(self._events.popleft())
        return out

    # ------------------------------------------------------------------ worker threads
    def _wanted_rect(self, win_w: int, win_h: int) -> tuple[int, int, int, int] | None:
        names = self.vision.regions_for(self.fsm.state.value if self._status == Status.RUNNING else "IDLE")
        rects = [self.profile.region(n).to_rect(win_w, win_h) for n in names
                 if self.profile.region(n).enabled and self.profile.region(n).is_valid()]
        if not rects:
            return None
        return union_rect(rects, 4, (win_w, win_h))

    def _capture_loop(self) -> None:
        perf = self.settings.performance
        while not self._stop_threads.is_set():
            t0 = time.monotonic()
            reeling = self._status == Status.RUNNING and self.fsm.state == State.REELING
            period = 1.0 / max(1, perf.reel_fps if reeling else perf.detection_fps)
            try:
                win = self.source.locate()
                if not win.found:
                    raise CaptureError("Game window not found - is Roblox open?")
                full = (not perf.roi_capture or self._status in (Status.MONITORING, Status.PAUSED)
                        or t0 - self._last_full >= perf.full_check_interval
                        or (self._preview_wanted and t0 - self._last_full >= 1.0 / max(1, perf.preview_fps))
                        or self.autocal.wants_frame(t0))
                rect = None if full else self._wanted_rect(win.width, win.height)
                frame = self.source.grab(win, rect)
                if rect is None:
                    self._last_full = t0
                frame.meta["capture_ms"] = (time.monotonic() - t0) * 1000
                item = frame
            except CaptureError as exc:
                item = _CaptureFailure(str(exc), "not found" in str(exc) or "minimised" in str(exc), t0)
            except Exception as exc:  # noqa: BLE001
                log.exception("Unexpected capture error")
                item = _CaptureFailure(f"Capture error: {exc}", False, t0)
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                try:
                    self._queue.get_nowait()  # drop the stale frame, keep latency low
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(item)
                except queue.Full:
                    pass
            delay = period - (time.monotonic() - t0)
            if isinstance(item, _CaptureFailure):
                delay = max(delay, 0.25)
            if delay > 0:
                self._stop_threads.wait(delay)

    def _process_loop(self) -> None:
        last = time.monotonic()
        fps = 0.0
        while not self._stop_threads.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            now = time.monotonic()
            dt = now - last
            last = now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt
            try:
                if isinstance(item, _CaptureFailure):
                    self._handle_capture_failure(item, now)
                else:
                    self._handle_frame(item, now)
            except Exception as exc:  # noqa: BLE001
                log.exception("Processing error")
                self.inputs.release_all()
                if self._status in (Status.RUNNING, Status.PAUSED):
                    self._snap.last_error = f"Internal error: {exc}"
                    self.stop_automation(f"internal error: {exc}")
            self._snap.fps = fps

    def _handle_capture_failure(self, f: _CaptureFailure, now: float) -> None:
        self.inputs.release_all()
        snap = self._snap
        snap.message = f.message
        snap.window_found = not f.window_missing
        snap.game_state = "No capture"
        if self._status not in (Status.RUNNING, Status.PAUSED):
            return
        with self._lock:
            self.fsm.update(Observation(ok=False, error=f.message), now)
        self.session.detection_errors += 1
        if f.window_missing:
            if self._window_missing_since is None:
                self._window_missing_since = now
                self._event("warning", f"{f.message} - inputs paused")
            if now - self._window_missing_since >= self.settings.capture.window_lost_timeout:
                snap.last_error = "Game window lost"
                self.stop_automation("game window lost")
        else:
            self._capture_failures += 1
            if self._capture_failures >= self.profile.timing.capture_failure_limit:
                snap.last_error = f.message
                self.stop_automation(f"capture failing repeatedly: {f.message}")

    def _handle_frame(self, frame: Frame, now: float) -> None:
        self._window_missing_since = None
        self._capture_failures = 0
        running = self._status == Status.RUNNING
        state = self.fsm.state.value if running else "IDLE"
        wanted = self.vision.regions_for(state) if (running and not frame.full) else None
        obs = self.vision.process(frame, wanted, state if running else None)
        message = ""
        self._autocal_tick(frame, obs, now)
        with self._lock:
            if self._status == Status.RUNNING:
                if self._last_active_tick is not None:
                    self.session.active_seconds += now - self._last_active_tick
                self._last_active_tick = now
                if self.settings.capture.require_focus and not obs.window_focused and not self.simulated:
                    if not self._focus_paused:
                        self._focus_paused = True
                        self.inputs.release_all()
                        self.fsm.reel.release()
                        self._event("warning", "Roblox lost focus - inputs paused until it is focused again")
                    message = "Waiting for Roblox to be focused"
                else:
                    if self._focus_paused:
                        self._focus_paused = False
                        self.vision.reset_background()
                        self.fsm.resync(now, "focus regained")
                    self.fsm.update(obs, now)
                if self.fsm.state == State.ERROR:
                    self._snap.last_error = self.fsm.history[-1][3] if self.fsm.history else "error"
                    self._on_fsm_error(frame, obs)
                elif not self.fsm.running and self._status == Status.RUNNING:
                    # Stopped by a module (session limit) or by the FSM itself.
                    self._status = Status.MONITORING
                    self._finish_session(self.fsm.stop_requested or "finished")
                    self._event("info", "Automation finished")
            else:
                self._last_active_tick = None
        snap = self._snap
        snap.status = self._status
        snap.fsm_state = self.fsm.state.value
        snap.observation = obs
        snap.game_state = obs.summary_state()
        snap.message = message
        snap.reel = copy.copy(self.fsm.reel.debug)
        snap.capture_ms = frame.meta.get("capture_ms", 0.0)
        snap.process_ms = obs.processing_ms
        snap.window_found = True
        snap.window_focused = obs.window_focused
        snap.simulated = self.simulated
        snap.held_inputs = tuple(sorted(self.inputs.held()[0] | self.inputs.held()[1]))
        snap.session = self.session
        snap.frame_id += 1
        if frame.full:
            snap.preview = frame
            snap.preview_obs = obs
            self._latest_image = frame.image

    # ------------------------------------------------------------------ routines
    def _grab_full_image(self):
        try:
            src = self.source or self._make_source()
            win = src.locate()
            return src.grab(win, None).image if win.found else None
        except Exception as exc:  # noqa: BLE001
            log.warning("Routine capture failed: %s", exc)
            return None

    def _to_screen(self, nx: float, ny: float) -> tuple[int, int]:
        try:
            win = (self.source or self._make_source()).locate()
            return int(win.left + nx * win.width), int(win.top + ny * win.height)
        except Exception:  # noqa: BLE001
            return 0, 0

    def _routine_runner(self) -> RoutineRunner:
        return RoutineRunner(RoutineContext(
            input=self.inputs, loadout=self.settings.loadout, rod_key=self.profile.equipment.rod_slot_key,
            to_screen=self._to_screen, grab=self._grab_full_image, sleep=lambda s: self._abort.wait(s),
            emit=self._on_event))

    def _on_watch_match(self, w, matches, text, image) -> None:
        msg = f"{w.name}: {', '.join(matches)}"
        self._event("watcher", msg + (f' - "{text[:100]}"' if text else ""))
        if w.notify_discord:
            self.notifier.send(f"{w.name} detected", f"**{', '.join(matches)}**\n> {text[:300]}", image=image,
                               key=f"{w.name}:{'|'.join(matches)}", min_gap=60)
        queued = self.trigger_routines_for_watcher(w.name)
        if queued:
            self._event("info", f"Queued routine(s) for {w.name}: {', '.join(queued)}")
        if w.pause_automation and self._status == Status.RUNNING:
            self.pause()
            self._event("warning", f"Paused because {msg}")

    def active_watchers(self) -> list[Watcher]:
        """Screen readers the current settings need: hunts, world readout, rod power, rod name."""
        st, out = self.settings, [w for w in self.settings.watchers if w.enabled]
        h = st.hunts
        names = list(dict.fromkeys(h.watched + h.custom))
        if names:
            out.append(Watcher("Hunts", enabled=True, kind="hunt", region=h.region, keywords="|".join(names),
                               interval_s=3, cooldown_min=10, notify_discord=h.discord, toast=h.toast,
                               pause_automation=h.pause))
        a = st.addons
        self.addons.cfg = a
        if a.totem.enabled:
            out.append(Watcher("World", enabled=True, kind="world", region=a.totem.world_region, interval_s=5,
                               notify_discord=False, toast=False))
        if a.sovereign.enabled:
            out.append(Watcher("Sovereign power", enabled=True, kind="power", region=a.sovereign.power_region,
                               interval_s=4, notify_discord=False, toast=False))
        if st.rod_detect.enabled:
            out.append(Watcher("Rod name", enabled=True, kind="rod", region=st.rod_detect.region, interval_s=8,
                               notify_discord=False, toast=False))
        return out

    def _on_watch_text(self, w, text: str, now: float) -> None:
        if w.kind == "world":
            self.addons.on_world_text(text, now)
        elif w.kind == "power":
            self.addons.on_power_text(text, now)

    def _on_rod_detected(self, name: str) -> None:
        self.detected_rod = name
        self._event("rod", f"Rod detected: {name}")
        if self.on_rod_detected:
            self.on_rod_detected(name)

    def request_profile(self, profile: Profile) -> None:
        """Switch profile now if idle, otherwise at the next safe point (never mid-minigame)."""
        if self._status in (Status.RUNNING, Status.PAUSED):
            self._pending_profile = profile
        else:
            self.set_profile(profile)

    def _apply_pending_profile(self) -> None:
        p, self._pending_profile = self._pending_profile, None
        if p is None:
            return
        with self._lock:
            self.profile = p
            self.vision = VisionEngine(p)
            f = self.fsm
            f.profile = p
            f.reel = ReelController(p.reel)
            f.minigame = MinigameSolver(p.minigame, f)
            f.modules = ModuleHost(p.modules)
        self._event("info", f"Switched to profile '{p.name}'")

    def _routines_safe_point(self, now: float) -> None:
        self._apply_pending_profile()
        for r in self.scheduler.due(self.settings.routines, now, self.session.catches):
            self.routine_running = r.name
            try:
                ok = self._routine_runner().run(r)
            finally:
                self.routine_running = ""
            self.scheduler.mark_run(r, time.monotonic(), self.session.catches)
            if not ok or self._abort.is_set():
                return
        self.addons.cfg = self.settings.addons
        for reason, r in self.addons.plan(time.monotonic()):
            self._event("info", f"Add-on: {reason}")
            self.routine_running = r.name
            try:
                ok = self._run_addon(r)
            finally:
                self.routine_running = ""
            self.addons.mark(r, time.monotonic())
            if not ok or self._abort.is_set():
                return
        self._ensure_lullaby_mode()

    def _run_addon(self, r: Routine) -> bool:
        runner = self._routine_runner()
        if r.note != "sovereign":
            return runner.run(r)
        # Sovereign: use relics until the power readout reaches the target (max 10 relics).
        s = self.settings.addons.sovereign
        for _ in range(10):
            seen = self.addons.world.power_updated
            if not runner.run(r):
                return False
            deadline = time.monotonic() + 8.0
            while self.addons.world.power_updated <= seen and time.monotonic() < deadline:
                if self._abort.wait(0.3):
                    return False
            p = self.addons.world.power
            if p is None or self.addons.world.power_updated <= seen:
                self._event("warning", "Sovereign: no power reading after the relic - check the power region")
                return True
            if p >= s.charge_up_to:
                self._event("info", f"Sovereign recharged to {p}%")
                return True
        return True

    def _ensure_lullaby_mode(self) -> None:
        """Lullaby rod: press the mode key until the chosen mode's name is on screen (once per session)."""
        m = self.profile.minigame
        want = m.lullaby_mode
        if m.kind != "lullaby" or not want or want == "Keep current" or self._lullaby_mode_set == want:
            return
        from fischmacro.vision.ocr import find_keywords
        runner = self._routine_runner()
        try:
            for i in range(len(LULLABY_MODES) + 1):
                boxes, _ = runner._ocr()
                if find_keywords(" ".join(b.text for b in boxes), [want]):
                    self._lullaby_mode_set = want
                    self._event("info", f"Lullaby mode: {want}" + (f" ({i} presses)" if i else ""))
                    return
                if not self.inputs.press_key(m.mode_key or "q") or self._abort.wait(0.8):
                    return
        except Exception:  # noqa: BLE001
            log.exception("Lullaby mode switch failed")
        self._lullaby_mode_set = want  # do not keep pressing every catch
        self._event("warning", f"Could not confirm Lullaby mode '{want}' on screen - left as is")

    def run_appraise(self, countdown: float = 3.0) -> str:
        """Auto Appraise: re-roll the held fish until it has one of the chosen traits."""
        if self._status in (Status.RUNNING, Status.PAUSED):
            return "Stop fishing first - appraising needs the fish in your hand"
        a = self.settings.addons.appraise
        if not a.traits:
            return "Pick at least one trait first"
        return self.run_routine_now("Auto Appraise", countdown, routine=self.addons.appraise_routine())

    def run_routine_now(self, name: str, countdown: float = 3.0, routine: Routine | None = None) -> str:
        """Queue (while fishing) or run (while stopped) a routine by name. Returns a status message."""
        routine = routine or next((r for r in self.settings.routines if r.name == name), None)
        if routine is None:
            return f"No routine named '{name}'"
        if self._status in (Status.RUNNING, Status.PAUSED):
            self.scheduler.trigger(name)
            return f"'{name}' will run after the current catch"
        if self.routine_running:
            return f"'{self.routine_running}' is already running"

        def worker():
            self.routine_running = name
            try:
                self._abort.clear()
                self.inputs.enable()
                if countdown and self._abort.wait(countdown):
                    return
                if self.settings.capture.require_focus and self.source is not None and not self.simulated:
                    win = self.source.locate()
                    if not win.focused:
                        self._event("warning", f"Routine '{name}' skipped: Roblox is not focused")
                        return
                self._routine_runner().run(routine)
            finally:
                self.routine_running = ""
                self.inputs.release_all()

        self.start_vision()
        threading.Thread(target=worker, name="routine", daemon=True).start()
        return f"Running '{name}' in {countdown:.0f} s - click into Roblox now"

    def trigger_routines_for_watcher(self, watcher_name: str) -> list[str]:
        names = [r.name for r in self.settings.routines if r.enabled and r.trigger == "watcher"
                 and r.watcher.strip().lower() == watcher_name.strip().lower()]
        for n in names:
            self.scheduler.trigger(n)
        return names

    # ------------------------------------------------------------------ auto calibration
    def start_autocalibration(self, seconds: float = 120.0) -> None:
        """Watch the screen until a reel minigame is seen, then calibrate the profile from it."""
        self.start_vision()
        self.autocal.clear()
        self.autocal_result = None
        self._autocal_wizard_until = time.monotonic() + seconds
        self.autocal_status = "Watching... cast and play one reel minigame manually (or start automation)."
        self._event("info", "Auto-calibration started - fish once so the minigame can be found")

    def cancel_autocalibration(self) -> None:
        self._autocal_wizard_until = 0.0
        self.autocal_status = "Auto-calibration cancelled."

    @property
    def autocalibrating(self) -> bool:
        return time.monotonic() < self._autocal_wizard_until

    def _autocal_tick(self, frame: Frame, obs: Observation, now: float) -> None:
        wizard = now < self._autocal_wizard_until
        running = self._status == Status.RUNNING
        st = self.fsm.state.value
        adapt = running and self.profile.detection.auto_adapt and st in ("SHAKE", "REELING")
        if self._autocal_wizard_until and not wizard and self.autocal_result is None and \
                self.autocal_status.startswith("Watching"):
            self.autocal_status = "Auto-calibration timed out - no reel minigame was seen."
        self.autocal.active = wizard or adapt
        if not self.autocal.active:
            if self.autocal.frames:
                self.autocal.clear()
            self._fish_missing_since = None
            return
        if frame.full:
            self.autocal.add(frame.image, now)
        if obs.shake.present:
            self._last_shake_seen = now
            if not wizard:
                self.autocal.clear()  # the reel starts after the last shake
        if obs.reel.ui_present and not obs.reel.fish_found:
            self._fish_missing_since = self._fish_missing_since or now
        else:
            self._fish_missing_since = None
        span = (self.autocal.frames[-1][0] - self.autocal.frames[0][0]) if len(self.autocal.frames) > 1 else 0.0
        if span < (2.0 if wizard else 0.9) or now - self._last_autocal_try < 0.5:
            return
        reel_lost = (st == "SHAKE" and now - self.fsm.ctx.entered > 1.2 and now - self._last_shake_seen > 0.6
                     and not obs.reel.ui_present)
        fish_lost = st == "REELING" and self._fish_missing_since is not None and now - self._fish_missing_since > 0.4
        if not (wizard or (adapt and (reel_lost or fish_lost))):
            return
        self._last_autocal_try = now
        res = self.autocal.run()
        if not res.ok or res.confidence < 0.45 or not self.autocal.validate(self.profile, res):
            return
        d = self.profile.detection
        before = {"bar": d.bar_color, "fish": d.fish_color}
        with self._lock:
            changed = apply_result(self.profile, res, regions=wizard or reel_lost)
            self.vision.reset_background()
        if wizard:
            self._autocal_wizard_until = 0.0
            self.autocal_result = res
            self.autocal_status = ("Calibrated: " + ", ".join(changed) + ".") if changed else \
                "Calibration confirmed - nothing needed to change."
            if res.notes:
                self.autocal_status += " " + " ".join(res.notes)
        if changed:
            self._event("autocal", ("Auto-calibrated " if wizard else "Adapted to new rod/skin: ") + ", ".join(changed))
            if self.on_profile_changed:
                self.on_profile_changed("autocal" if wizard else "adapt",
                                        {"old_bar": before["bar"], "old_fish": before["fish"],
                                         "new_bar": d.bar_color, "new_fish": d.fish_color})

    def _on_fsm_error(self, frame: Frame, obs: Observation) -> None:
        self.inputs.release_all()
        self._status = Status.MONITORING
        self._finish_session(f"error: {self._snap.last_error}")
        if self.settings.logging.snapshot_on_error and frame.full:
            try:
                from fischmacro.diagnostics.snapshot import save_snapshot
                save_snapshot(frame, self.profile, obs, note=self._snap.last_error)
            except Exception:  # noqa: BLE001
                log.exception("Could not save error snapshot")

    def snapshot(self) -> EngineSnapshot:
        s = copy.copy(self._snap)
        s.status = self._status
        return s

    def capture_full_frame(self) -> Frame:
        """One-off full capture for calibration and diagnostics (works without vision running)."""
        src = self.source if self._threads else self._make_source()
        win = src.locate()
        if not win.found:
            raise CaptureError("Game window not found - is Roblox open?")
        return src.grab(win, None)
