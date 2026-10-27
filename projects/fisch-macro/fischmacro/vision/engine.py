"""Runs the configured detectors on a frame and returns one Observation."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from fischmacro.profiles.schema import Profile
from fischmacro.vision import detectors as d
from fischmacro.vision import minigames as mg
from fischmacro.vision.frame import Frame
from fischmacro.vision.reel_adaptive import AdaptiveReel

# Regions each automation state needs. Capturing only these keeps CPU use low.
STATE_REGIONS: dict[str, tuple[str, ...]] = {
    "IDLE": ("reel", "progress", "shake", "cast"),
    "CASTING": ("cast", "reel"),
    "WAITING_FOR_BITE": ("shake", "reel"),
    "SHAKE": ("shake", "reel"),
    "REELING": ("reel", "progress", "catch_popup", "mini", "mini_target"),
    "CATCH_CONFIRMED": ("reel", "catch_popup"),
    "RECOVERY": ("reel", "shake", "disconnect", "reconnect_button"),
    "ERROR": ("reel", "disconnect"),
}
ALL_DETECTORS = ("reel", "progress", "shake", "cast", "catch_popup", "disconnect")


@dataclass
class Observation:
    timestamp: float = 0.0
    ok: bool = False                      # a frame was captured and processed
    client_size: tuple[int, int] = (0, 0)
    screen_origin: tuple[int, int] = (0, 0)
    window_found: bool = False
    window_focused: bool = False
    reel: d.ReelResult = field(default_factory=d.ReelResult)
    progress: d.FillResult = field(default_factory=d.FillResult)
    shake: d.ShakeResult = field(default_factory=d.ShakeResult)
    cast: d.FillResult = field(default_factory=d.FillResult)
    catch_popup: d.DialogResult = field(default_factory=d.DialogResult)
    disconnect: d.DialogResult = field(default_factory=d.DialogResult)
    timing: mg.TimingResult = field(default_factory=mg.TimingResult)
    match: mg.MatchResult = field(default_factory=mg.MatchResult)
    targets: mg.TargetsResult = field(default_factory=mg.TargetsResult)
    frozen_seconds: float = 0.0
    checked: tuple[str, ...] = ()
    processing_ms: float = 0.0
    error: str = ""

    def summary_state(self) -> str:
        """Best guess of what the game is showing, for display only."""
        if not self.ok:
            return "No capture"
        if self.disconnect.detected:
            return "Disconnected / error dialog"
        if self.reel.ui_present:
            return "Reel minigame"
        if self.shake.present:
            return "Shake prompt"
        if self.cast.present:
            return "Casting power bar"
        return "Idle / waiting"

    def confidence(self) -> float:
        if self.reel.ui_present:
            return self.reel.confidence
        if self.shake.present:
            return self.shake.confidence
        if self.cast.present:
            return self.cast.confidence
        return 1.0 if self.ok else 0.0


class VisionEngine:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.templates = d.TemplateCache()
        self._last_small: np.ndarray | None = None
        self._frozen_since: float | None = None
        self._shake_ref: np.ndarray | None = None
        self._shake_ref_t = -1e9
        self.adaptive = AdaptiveReel()

    def regions_for(self, state: str) -> tuple[str, ...]:
        return STATE_REGIONS.get(state, ALL_DETECTORS)

    def reset_background(self) -> None:
        self._shake_ref = None
        self._shake_ref_t = -1e9

    def _update_shake_reference(self, frame: Frame, region, state: str | None, found: bool) -> None:
        """While waiting for a bite, remember shake-coloured background so it is never clicked."""
        if state in ("CASTING", "IDLE", None):
            self._shake_ref = None
            self._shake_ref_t = -1e9
            return
        if state != "WAITING_FOR_BITE" or found or frame.timestamp - self._shake_ref_t < 0.5:
            return
        crop = frame.crop(region)
        if crop is None:
            return
        mask = cv2.dilate(d.shake_color_mask(crop, self.profile.detection), np.ones((5, 5), np.uint8))
        # Keep only what was there in the previous look too: static background stays excluded, while a shake
        # button that has just appeared (or a splash that has just gone) never ends up in the reference.
        if self._shake_ref is None or self._shake_ref.shape != mask.shape:
            self._shake_ref = mask
        else:
            self._shake_ref = cv2.bitwise_and(self._shake_ref, mask)
        self._shake_ref_t = frame.timestamp

    def process(self, frame: Frame, wanted: tuple[str, ...] | None = None, state: str | None = None) -> Observation:
        t0 = time.perf_counter()
        p = self.profile
        cfg = p.detection
        wanted = wanted or ALL_DETECTORS
        obs = Observation(timestamp=frame.timestamp, ok=True, client_size=frame.client_size,
                          screen_origin=frame.screen_origin,
                          window_found=frame.meta.get("window_found", True),
                          window_focused=frame.meta.get("window_focused", True))
        checked = []
        ch = frame.client_size[1]

        def region(name):
            r = p.region(name)
            return r if r.enabled and r.is_valid() else None

        if "reel" in wanted and (r := region("reel")):
            crop = frame.crop(r)
            obs.reel = d.detect_reel(crop, cfg)
            if getattr(cfg, "fish_any_colour", True):
                obs.reel = self._pick_reel(obs.reel, self.adaptive.update(crop))
            checked.append("reel")
        if "progress" in wanted and (r := region("progress")):
            pcrop = frame.crop(r)
            obs.progress = d.detect_progress(pcrop, cfg)
            if not obs.progress.present and getattr(cfg, "fish_any_colour", True):
                obs.progress = d.detect_progress_auto(pcrop)
            checked.append("progress")
        if "shake" in wanted and (r := region("shake")):
            obs.shake = d.detect_shake(frame, r, cfg, self.templates, exclude=self._shake_ref)
            obs.shake.targets = [t for t in obs.shake.targets if t.confidence >= cfg.min_confidence]
            self._update_shake_reference(frame, r, state, obs.shake.present)
            checked.append("shake")
        if "cast" in wanted and (r := region("cast")):
            obs.cast = d.detect_cast(frame.crop(r), cfg)
            checked.append("cast")
        if "catch_popup" in wanted and cfg.catch_template and (r := region("catch_popup")):
            obs.catch_popup = d.detect_template_popup(frame.crop(r), cfg.catch_template, cfg.catch_template_ref_h,
                                                      ch, cfg.template_threshold, self.templates)
            checked.append("catch_popup")
        mcfg = p.minigame
        if mcfg.kind != "none" and "mini" in wanted and (r := region("mini")):
            if mcfg.kind == "lullaby":
                mcrop = frame.crop(r)
                obs.timing = mg.detect_timing(mcrop, mcfg.pointer_color, mcfg.pointer_tolerance,
                                              mcfg.lit_color, mcfg.lit_tolerance, mcfg.axis)
                if (not obs.timing.present or not obs.timing.segments) and getattr(cfg, "fish_any_colour", True):
                    auto = mg.detect_timing_auto(mcrop, mcfg.axis)
                    if auto.present:
                        obs.timing = auto
            elif mcfg.kind == "stellarwave" and (t := region("mini_target")):
                obs.match = mg.detect_match(frame, t, r, mcfg.symbol_color, mcfg.symbol_tolerance)
            elif mcfg.kind == "targets":
                obs.targets = mg.detect_targets(frame, r, mcfg.target_color, mcfg.target_tolerance)
            checked.append("mini")
        if frame.full and cfg.disconnect_detection and (r := region("disconnect")):
            obs.disconnect = d.detect_disconnect(frame.crop(r), cfg)
            checked.append("disconnect")
        if frame.full:
            obs.frozen_seconds = self._frozen(frame)
        obs.checked = tuple(checked)
        obs.processing_ms = (time.perf_counter() - t0) * 1000
        return obs

    @staticmethod
    def _pick_reel(colour: d.ReelResult, shape: d.ReelResult) -> d.ReelResult:
        """Trust calibrated colours when they agree with the shape tracker; otherwise the shape tracker."""
        if colour.present and colour.bar_found and colour.confidence >= 0.5:
            if not shape.fish_found or abs(colour.fish_x - shape.fish_x) < 0.03:
                return colour
        if shape.bar_found:
            return shape
        if colour.present and colour.confidence >= 0.5:
            return colour
        if shape.ui_present:
            return shape
        return colour

    def _frozen(self, frame: Frame) -> float:
        small = cv2.resize(cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY), (64, 36), interpolation=cv2.INTER_AREA)
        now = frame.timestamp
        if self._last_small is not None and self._last_small.shape == small.shape and \
                float(cv2.absdiff(small, self._last_small).mean()) < 0.4:
            if self._frozen_since is None:
                self._frozen_since = now
        else:
            self._frozen_since = None
        self._last_small = small
        return 0.0 if self._frozen_since is None else max(0.0, now - self._frozen_since)
