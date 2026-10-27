"""Finite-state machine for the fishing loop.

The machine is driven by observations: ``update(observation, now)`` is called
once per processed frame. Each state decides from what it *sees* (plus
timeouts) when to move on; nothing is a blind sequence of sleeps. Whenever the
game state is unclear the machine releases input and waits, retries, or stops.
"""
from __future__ import annotations

import logging
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from fischmacro.automation.minigame_solvers import MinigameSolver
from fischmacro.automation.modules import ModuleContext, ModuleHost
from fischmacro.automation.reel_controller import ReelController
from fischmacro.input.controller import InputController
from fischmacro.profiles.schema import Profile
from fischmacro.vision.engine import Observation

log = logging.getLogger(__name__)


class State(str, Enum):
    IDLE = "IDLE"
    CASTING = "CASTING"
    WAITING_FOR_BITE = "WAITING_FOR_BITE"
    SHAKE = "SHAKE"
    REELING = "REELING"
    CATCH_CONFIRMED = "CATCH_CONFIRMED"
    RECOVERY = "RECOVERY"
    ERROR = "ERROR"


# Allowed transitions; anything else is a programming error and is refused.
TRANSITIONS: dict[State, set[State]] = {
    State.IDLE: {State.CASTING, State.RECOVERY},
    State.CASTING: {State.WAITING_FOR_BITE, State.REELING, State.RECOVERY, State.ERROR, State.IDLE},
    State.WAITING_FOR_BITE: {State.SHAKE, State.REELING, State.RECOVERY, State.ERROR, State.IDLE},
    State.SHAKE: {State.REELING, State.RECOVERY, State.ERROR, State.IDLE},
    State.REELING: {State.CATCH_CONFIRMED, State.RECOVERY, State.ERROR, State.IDLE},
    State.CATCH_CONFIRMED: {State.CASTING, State.REELING, State.RECOVERY, State.ERROR, State.IDLE},
    State.RECOVERY: {State.CASTING, State.SHAKE, State.REELING, State.RECOVERY, State.ERROR, State.IDLE},
    State.ERROR: {State.IDLE},
}


@dataclass
class _Tracked:
    x: float
    y: float
    count: int
    seen: float


@dataclass
class CycleInfo:
    started: float = 0.0
    perfect_cast: bool | None = None
    shake_clicks: int = 0
    last_progress: float | None = None
    max_progress: float = 0.0
    catch_popup: bool = False


@dataclass
class FsmContext:
    """State-local scratch values, reset on every transition."""
    entered: float = 0.0
    phase: int = 0
    t_mark: float = 0.0
    last_fill: float = 0.0
    cast_seen: bool = False
    tracked: list[_Tracked] = field(default_factory=list)
    recent_clicks: list[tuple[float, float, float]] = field(default_factory=list)
    last_click: float = -1e9
    last_nav: float = -1e9
    last_reel_ui: float = 0.0
    last_fish: float = 0.0
    reason: str = ""
    attempts: int = 0
    jitter: float | None = None  # random timing scale for this cast
    bar_center: float | None = None  # last clearly seen catch bar (reeling)
    bar_seen: float = 0.0
    fallback_warned: bool = False


class FishingStateMachine:
    def __init__(self, profile: Profile, inputs: InputController,
                 emit: Callable[..., None] | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 min_switch_interval: float = 0.0):
        self.profile = profile
        self.input = inputs
        self._emit_cb = emit or (lambda kind, msg, **data: None)
        self.sleep = sleep
        self.min_switch_interval = min_switch_interval
        self.modules = ModuleHost(profile.modules)
        self.reel = ReelController(profile.reel)
        self.minigame = MinigameSolver(profile.minigame, self)
        self.state = State.IDLE
        self.ctx = FsmContext()
        self.cycle = CycleInfo()
        self.running = False
        self.consecutive_recoveries = 0
        self.reconnect_attempts = 0
        self.stop_requested: str = ""
        self.last_obs: Observation | None = None
        self.history: list[tuple[float, State, State, str]] = []
        self.safe_point_hooks: list = []  # callables(now) run between catches (routines)

    # ------------------------------------------------------------------ control
    def emit(self, kind: str, message: str, **data) -> None:
        try:
            self._emit_cb(kind, message, **data)
        except Exception:  # noqa: BLE001
            log.exception("Event handler failed")

    def start(self, now: float) -> None:
        self.running = True
        self.stop_requested = ""
        self.consecutive_recoveries = 0
        self.reconnect_attempts = 0
        self.input.enable()
        self.modules = ModuleHost(self.profile.modules)
        self.modules.call("on_session_start", self._module_ctx(now))
        self._go(State.CASTING, now, "start")

    def stop(self, now: float | None = None, reason: str = "stopped") -> None:
        self.input.release_all()
        self.reel.release()
        self.running = False
        if self.state != State.IDLE:
            self._go(State.IDLE, now if now is not None else time.monotonic(), reason, force=True)

    def resync(self, now: float, reason: str = "resume") -> None:
        """Re-enter the loop after a pause: look at the screen before doing anything."""
        self.input.release_all()
        self.reel.release()
        self.running = True
        self._go(State.RECOVERY, now, reason, count=False, force=True)

    def _go(self, new: State, now: float, reason: str = "", *, count: bool = True, force: bool = False) -> None:
        old = self.state
        if not force and new not in TRANSITIONS[old]:
            raise RuntimeError(f"Illegal transition {old.value} -> {new.value}")
        self.history.append((now, old, new, reason))
        del self.history[:-200]
        self.state = new
        self.ctx = FsmContext(entered=now, reason=reason)
        if new == State.RECOVERY:
            self.input.release_all()
            self.reel.release()
            if count:
                self.consecutive_recoveries += 1
                self.emit("recovery", f"Recovery: {reason}", reason=reason)
                if self.consecutive_recoveries > self.profile.timing.max_consecutive_recoveries:
                    self._error(now, f"Too many recoveries in a row (last: {reason})")
                    return
        if new == State.ERROR:
            self.input.release_all()
            self.reel.release()
        if new == State.CASTING:
            self.cycle = CycleInfo(started=now)
        if new == State.REELING:
            self.reel.reset()
            self.minigame.reset()
            self.ctx.last_reel_ui = now
            self.ctx.last_fish = now
        self.emit("state", f"{old.value} -> {new.value}" + (f" ({reason})" if reason else ""),
                  old=old.value, new=new.value, reason=reason)

    def _error(self, now: float, message: str) -> None:
        self.input.release_all()
        self.reel.release()
        self.running = False
        self.emit("error", message)
        self._go(State.ERROR, now, message, force=True)

    def _elapsed(self, now: float) -> float:
        return now - self.ctx.entered

    # ------------------------------------------------------------------ helpers
    def _screen(self, obs: Observation, nx: float, ny: float) -> tuple[int, int]:
        cw, ch = obs.client_size
        return int(obs.screen_origin[0] + nx * cw), int(obs.screen_origin[1] + ny * ch)

    def _click_client(self, nx: float, ny: float) -> bool:
        obs = self.last_obs
        if obs is None or not obs.ok:
            return False
        x, y = self._screen(obs, nx, ny)
        return self.input.click(x, y)

    def _module_ctx(self, now: float) -> ModuleContext:
        return ModuleContext(input=self.input, profile=self.profile, now=now, emit=self.emit,
                             click_client=self._click_client, press_key=self.input.press_key,
                             sleep=self.sleep, request_stop=self._request_stop, observation=self.last_obs)

    def _request_stop(self, reason: str) -> None:
        if not self.stop_requested:
            self.stop_requested = reason
            self.emit("info", reason)

    def _confident(self, conf: float) -> bool:
        return conf >= self.profile.detection.min_confidence

    # ------------------------------------------------------------------ main entry
    def update(self, obs: Observation, now: float) -> None:
        self.last_obs = obs
        if not self.running or self.state in (State.IDLE, State.ERROR):
            return
        if not obs.ok:
            # Never act on a frame we could not see; the runner handles capture errors.
            self.input.release_all()
            self.reel.release()
            return
        self.modules.call("on_tick", self._module_ctx(now))
        if self.stop_requested and self.state not in (State.REELING,):
            self.stop(now, self.stop_requested)
            return
        if obs.disconnect.detected and not (self.state == State.RECOVERY and self.ctx.reason == "disconnect"):
            self.emit("disconnect", "Disconnect / error dialog detected")
            if self.modules.get("auto_reconnect") and self.profile.region("reconnect_button").enabled:
                self._go(State.RECOVERY, now, "disconnect", force=True)
            else:
                self._error(now, "Disconnect or error dialog detected - automation stopped")
            return
        getattr(self, f"_on_{self.state.value.lower()}")(obs, now)

    # ------------------------------------------------------------------ states
    def _on_casting(self, obs: Observation, now: float) -> None:
        cfg = self.profile.casting
        c = self.ctx
        t = self._elapsed(now)
        if c.phase == 0:
            if self.profile.equipment.equip_before_cast and self.profile.equipment.rod_slot_key:
                self.input.press_key(self.profile.equipment.rod_slot_key)
            if cfg.move_mouse_to_center:
                x, y = self._screen(obs, 0.5, 0.45)
                self.input.move_to(x, y)
            c.phase = 1
            return
        if c.phase == 1:
            if obs.reel.ui_present:
                self._go(State.REELING, now, "minigame already active")
                return
            if c.jitter is None:
                c.jitter = random.uniform(1 - cfg.jitter, 1 + cfg.jitter)
            if t >= cfg.pre_cast_delay * c.jitter:
                if self.input.mouse_down():
                    c.phase, c.t_mark = 2, now
            return
        held = now - c.t_mark
        if obs.reel.ui_present:
            self.input.mouse_up()
            self._go(State.REELING, now, "minigame appeared while casting")
            return
        release, perfect = False, None
        fill = obs.cast.fill if (obs.cast.present and self._confident(obs.cast.confidence)) else None
        if fill is not None:
            c.cast_seen = True
        if cfg.mode == "perfect" and fill is not None:
            if fill >= cfg.perfect_threshold:
                release, perfect = True, True
            elif c.last_fill >= 0.85 and fill < c.last_fill - 0.02:
                release, perfect = True, False  # passed the peak between frames
            c.last_fill = fill
        scale = c.jitter or 1.0
        if not release and cfg.mode == "normal" and held >= cfg.normal_hold * scale:
            release = True
        if not release and cfg.mode != "normal" and (cfg.mode == "timed" or not c.cast_seen) and \
                held >= cfg.hold_seconds * (scale if cfg.mode == "timed" else 1.0):
            release = True
            if cfg.mode == "perfect" and not c.cast_seen:
                self.emit("warning", "Cast power bar not detected - used timed fallback")
        if not release and held >= cfg.max_hold_seconds:
            release = True
            self.emit("warning", "Cast held for the maximum time - releasing")
        if release:
            self.input.mouse_up()
            self.cycle.perfect_cast = perfect
            self.emit("cast", "Cast" + (" (perfect)" if perfect else ""), perfect=perfect, held=held)
            self._go(State.WAITING_FOR_BITE, now, "cast released")

    def _on_waiting_for_bite(self, obs: Observation, now: float) -> None:
        if obs.reel.ui_present:
            self._go(State.REELING, now, "minigame detected")
            return
        mode = self.profile.shake.mode
        if mode == "click" and obs.shake.present:
            self._go(State.SHAKE, now, "shake prompt detected")
            return
        if mode == "navigation" and self._elapsed(now) >= self.profile.shake.nav_start_delay:
            self._go(State.SHAKE, now, "navigation shake")
            return
        if self._elapsed(now) >= self.profile.timing.bite_timeout:
            self._go(State.RECOVERY, now, "no bite")

    def _on_shake(self, obs: Observation, now: float) -> None:
        cfg = self.profile.shake
        c = self.ctx
        if obs.reel.ui_present:
            if cfg.mode == "navigation" and cfg.nav_toggle_key and c.phase == 1:
                self.input.press_key(cfg.nav_toggle_key)  # leave UI navigation again
            self._go(State.REELING, now, "minigame detected")
            return
        if self._elapsed(now) >= self.profile.timing.shake_timeout:
            self._go(State.RECOVERY, now, "shake timeout")
            return
        if cfg.mode == "navigation":
            if c.phase == 0:
                if cfg.nav_toggle_key:
                    self.input.press_key(cfg.nav_toggle_key)
                c.phase = 1
                return
            if now - c.last_nav >= cfg.nav_press_interval:
                self.input.press_key(cfg.nav_confirm_key)
                c.last_nav = now
            return

        # click mode: track targets across frames and click stable, not-recently-clicked ones
        r2 = 0.02 ** 2
        updated: list[_Tracked] = []
        for tgt in obs.shake.targets:
            prev = next((p for p in c.tracked if (p.x - tgt.x) ** 2 + (p.y - tgt.y) ** 2 <= r2), None)
            updated.append(_Tracked(tgt.x, tgt.y, (prev.count + 1) if prev else 1, now))
        c.tracked = updated
        c.recent_clicks = [rc for rc in c.recent_clicks if now - rc[2] < cfg.cooldown_seconds]
        if now - c.last_click < cfg.click_interval:
            return
        for tr in sorted(c.tracked, key=lambda t: -t.count):
            if tr.count < cfg.persistence_frames:
                continue
            if any(math.hypot(tr.x - rx, tr.y - ry) <= cfg.cooldown_radius for rx, ry, _ in c.recent_clicks):
                continue
            x, y = self._screen(obs, tr.x, tr.y)
            if self.input.click(x, y):
                c.last_click = now
                c.recent_clicks.append((tr.x, tr.y, now))
                self.cycle.shake_clicks += 1
                self.emit("shake", f"Shake click at ({tr.x:.3f}, {tr.y:.3f})", x=tr.x, y=tr.y)
            break

    def _on_reeling(self, obs: Observation, now: float) -> None:
        cfg = self.profile.reel
        c = self.ctx
        if obs.catch_popup.detected:
            self.cycle.catch_popup = True
        if obs.reel.ui_present:
            c.last_reel_ui = now
            if obs.reel.bar_found and obs.reel.bar_confidence >= cfg.min_confidence:
                c.bar_center, c.bar_seen = obs.reel.bar_center, now
            if obs.progress.present and self._confident(obs.progress.confidence):
                self.cycle.last_progress = obs.progress.fill
                self.cycle.max_progress = max(self.cycle.max_progress, obs.progress.fill)
        mini = self.profile.minigame
        steer = mini.kind == "none" or mini.keep_reeling
        if obs.reel.present and obs.reel.confidence >= cfg.min_confidence and not steer:
            c.last_fish = now  # rod minigame only: the bar is left alone
        elif obs.reel.present and obs.reel.confidence >= cfg.min_confidence:
            c.last_fish = now
            hold = self.reel.update(obs.reel.fish_x, obs.reel.bar_left, obs.reel.bar_right, now,
                                    obs.reel.confidence, self.min_switch_interval)
            if hold:
                self.input.mouse_down()
            else:
                self.input.mouse_up()
        elif steer and obs.reel.ui_present and obs.reel.fish_found and \
                obs.reel.fish_confidence >= cfg.min_confidence:
            # Fish is clear but the bar is not (see-through or recoloured bar): steer on the fish
            # against the last bar position we saw, like a simple pixel macro would.
            c.last_fish = now
            ref = c.bar_center if (c.bar_center is not None and now - c.bar_seen < 0.6) else 0.5
            hold = obs.reel.fish_x > ref
            if hold:
                self.input.mouse_down()
            else:
                self.input.mouse_up()
            if not c.fallback_warned:
                c.fallback_warned = True
                self.emit("warning", "Catch bar not clear - following the fish only. Run Auto-calibrate for smoother tracking")
        else:
            # Unsure where the fish is: do not keep holding blindly.
            if self.input.is_held():
                self.input.mouse_up()
            self.reel.release()
            if obs.reel.ui_present and now - c.last_fish >= cfg.lost_fish_timeout and c.phase == 0:
                c.phase = 1
                self.emit("warning", "Fish indicator lost - releasing input until it is found again")
        if mini.kind != "none" and obs.reel.ui_present:
            self.minigame.update(obs, now)
        if now - c.last_reel_ui >= cfg.end_grace:
            self._finish_reel(now)
            return
        if self._elapsed(now) >= self.profile.timing.reel_timeout:
            self._go(State.RECOVERY, now, "reel timeout")

    def _finish_reel(self, now: float) -> None:
        self.input.mouse_up()
        self.reel.release()
        cfg = self.profile.reel
        p = self.cycle.last_progress
        if self.cycle.catch_popup:
            outcome = "success"
        elif p is None:
            outcome = "unconfirmed"
        elif p >= cfg.success_threshold:
            outcome = "success"
        elif p <= cfg.fail_threshold:
            outcome = "failure"
        else:
            outcome = "unconfirmed"
        self.consecutive_recoveries = 0
        duration = now - self.cycle.started
        label = {"success": "Catch confirmed", "failure": "Fish escaped", "unconfirmed": "Cycle finished (outcome unconfirmed)"}[outcome]
        self.emit("cycle", f"{label} in {duration:.1f}s", outcome=outcome, duration=duration,
                  progress=p, perfect_cast=self.cycle.perfect_cast, shake_clicks=self.cycle.shake_clicks)
        self.modules.call("on_cycle_complete", self._module_ctx(now), outcome)
        self._go(State.CATCH_CONFIRMED, now, outcome)

    def _on_catch_confirmed(self, obs: Observation, now: float) -> None:
        if obs.reel.ui_present and self._elapsed(now) > 0.3:
            self._go(State.REELING, now, "minigame reappeared")
            return
        if self._elapsed(now) < self.profile.timing.post_catch_delay:
            return
        if self.stop_requested:
            self.stop(now, self.stop_requested)
            return
        # Safe point: modules and routines may send input here, never during a minigame.
        self.modules.call("at_safe_point", self._module_ctx(now))
        for hook in list(self.safe_point_hooks):
            try:
                hook(now)
            except Exception:  # noqa: BLE001 - a failing routine must not break fishing
                log.exception("Safe-point hook failed")
            if not self.running:
                return
        self._go(State.CASTING, now, "next cast")

    def _on_recovery(self, obs: Observation, now: float) -> None:
        c = self.ctx
        t = self._elapsed(now)
        timing = self.profile.timing
        if c.reason == "disconnect":
            self._recover_disconnect(obs, now)
            return
        # Look before acting: the game may already be in a known state.
        if obs.reel.ui_present and t > 0.2:
            self._go(State.REELING, now, "resynced to minigame", count=False)
            return
        if self.profile.shake.mode == "click" and obs.shake.present and t > 0.2:
            self._go(State.SHAKE, now, "resynced to shake", count=False)
            return
        if c.phase == 0 and t >= min(0.5, timing.recovery_delay):
            if timing.recovery_click and c.reason == "no bite":
                self._click_client(0.5, 0.45)
            eq = self.profile.equipment
            if eq.reequip_on_recovery and eq.rod_slot_key:
                self.input.press_key(eq.rod_slot_key)
                self.sleep(0.4)
                self.input.press_key(eq.rod_slot_key)
            c.phase = 1
            return
        if t >= timing.recovery_delay:
            self._go(State.CASTING, now, "recovered")

    def _recover_disconnect(self, obs: Observation, now: float) -> None:
        c = self.ctx
        mod = self.modules.get("auto_reconnect")
        t = self._elapsed(now)
        if mod is None:
            self._error(now, "Disconnected")
            return
        if t >= float(mod.get("timeout")):
            self._error(now, "Reconnect timed out")
            return
        if c.phase == 0 and t >= float(mod.get("delay")):
            if self.reconnect_attempts >= int(mod.get("max_attempts")):
                self._error(now, "Reconnect attempts exhausted")
                return
            self.reconnect_attempts += 1
            cx, cy = self.profile.region("reconnect_button").center()
            self.emit("recovery", f"Clicking Reconnect (attempt {self.reconnect_attempts})")
            self._click_client(cx, cy)
            c.phase, c.t_mark = 1, now
            return
        if c.phase == 1 and obs.ok and not obs.disconnect.detected and now - c.t_mark > 1.0:
            c.phase, c.t_mark = 2, now
            self.emit("info", "Disconnect dialog gone - waiting for the game to load")
        if c.phase == 2 and now - c.t_mark >= max(5.0, self.profile.timing.recovery_delay):
            self._go(State.CASTING, now, "reconnected")
