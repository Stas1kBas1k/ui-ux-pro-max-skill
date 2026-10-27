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

    def regions_for(self, state: str) -> tuple[str, ...]:
        return STATE_REGIONS.get(state, ALL_DETECTORS)

    def reset_background(self) -> None:
        self._shake_ref = None
        self._shake_ref_t = -1e9

    def _update_shake_reference(self, frame: Frame, region, state: str | None, found: bool) -> None:
        """While waiting for a bite, remember shake-coloured background so it is never clicked."""
        if state in ("CASTING", "IDLE", None):
            self._shake_ref = None
            return
        if state != "WAITING_FOR_BITE" or found or frame.timestamp - self._shake_ref_t < 1.0:
            return
        crop = frame.crop(region)
        if crop is None:
            return
        mask = d.shake_color_mask(crop, self.profile.detection)
        self._shake_ref = cv2.dilate(mask, np.ones((5, 5), np.uint8))
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
            obs.reel = d.detect_reel(frame.crop(r), cfg)
            checked.append("reel")
        if "progress" in wanted and (r := region("progress")):
            obs.progress = d.detect_progress(frame.crop(r), cfg)
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
                obs.timing = mg.detect_timing(frame.crop(r), mcfg.pointer_color, mcfg.pointer_tolerance,
                                              mcfg.lit_color, mcfg.lit_tolerance, mcfg.axis)
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
