"""Runs the configured detectors on a frame and returns one Observation."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from fischmacro.profiles.schema import Region, Profile
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
    "REELING": ("reel", "progress", "catch_popup", "mini", "mini_target", "reel_wide"),
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
    zodiac: object = None                 # Stellarwave: ZodiacObs (next sign and where it is on the strip)
    drops: tuple = ()                     # falling objects to catch with the bar (vision/falling.py Drop)
    prompt_image: object = None           # crop around a rod event, for reading its key prompt (MiguRod)
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
        from fischmacro.vision.shake_verify import ShakeVerifier
        self.shake_verifier = ShakeVerifier()
        from fischmacro.vision.lullaby_gauge import LullabyGauge
        from fischmacro.vision.falling import FallingObjects
        self.lullaby_gauge = LullabyGauge()
        self.falling = FallingObjects()
        self.verify_shake = True  # read the word before a shake click (off in the simulator: no real text)
        # Lullaby: the old lit-colour reader is only for the test game. On the real game it clicked on the red
        # part when the gauge was not found, so there nothing is clicked until the gauge is found.
        self.lullaby_fallback = True
        self.test_kind: str | None = None  # manual test mode: run this rod mechanic's detector whatever the profile

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
        kind = self.test_kind or p.minigame.kind
        if self.test_kind:
            wanted = tuple(dict.fromkeys(tuple(wanted) + ("reel", "mini", "reel_wide")))
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
            shape_ok = getattr(cfg, "fish_any_colour", True)  # colour-only profiles skip the shape readers
            if not shape_ok:
                pass
            elif cfg.reel_mode == "capsule" and (rw := region("reel_wide")):
                self._capsule_reel(frame, obs, r, rw)
            else:
                self._refine_fish(frame, obs, r)
                if kind == "falling" and obs.reel.ui_present:
                    from fischmacro.vision.falling import FallingObjects
                    obs.drops = tuple(self.falling.update(frame.crop(FallingObjects.band_region(r)), frame.timestamp))
                if kind == "migu" and obs.reel.ui_present and crop is not None:
                    from fischmacro.vision.reel_edges import find_marks
                    rr = obs.reel
                    obs.reel.marks = tuple(find_marks(crop, rr.fish_x if rr.fish_found else None,
                                                      (rr.bar_left, rr.bar_right) if rr.bar_found else None))
            self._sanity(obs, wide=cfg.reel_mode == "capsule")
            self._reel_gate(crop, obs, state, frame.timestamp)
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
            if self.verify_shake and obs.shake.targets and not cfg.shake_template:
                obs.shake.targets = self.shake_verifier.filter(frame.image, obs.shake.targets, frame.client_size,
                                                                origin=frame.origin)
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
        if kind != "none" and "mini" in wanted and (r := region("mini")):
            if kind == "migu":
                # the counterattack bar sits above the reel; search a taller box and find the red bar in it
                area = Region(r.x, max(0.0, r.y - 0.10), r.w, min(1.0, r.h + 0.14))
                acrop = frame.crop(area)
                if acrop is None:
                    acrop = frame.crop(r)
                obs.timing = mg.detect_migu(acrop)
                if obs.timing.present:
                    obs.prompt_image = acrop
            elif kind == "lullaby" and (rr := region("reel")) and \
                    (g := self._lullaby_gauge(frame, rr)).present:
                obs.timing = g
            elif kind == "lullaby" and self.lullaby_fallback:
                mcrop = frame.crop(r)
                obs.timing = mg.detect_timing(mcrop, mcfg.pointer_color, mcfg.pointer_tolerance,
                                              mcfg.lit_color, mcfg.lit_tolerance, mcfg.axis)
                if (not obs.timing.present or not obs.timing.segments) and getattr(cfg, "fish_any_colour", True):
                    auto = mg.detect_timing_auto(mcrop, mcfg.axis)
                    if auto.present:
                        obs.timing = auto
            elif kind == "stellarwave" and (rw := region("reel_wide")):
                obs.zodiac = self._zodiac(frame, rw)
            elif kind == "targets":
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
    def _sanity(obs: "Observation", wide: bool = False) -> None:
        """A fish or bar outside the track is not the reel (player's screenshot: the bait text read as a reel
        with the fish at 1.17 of its width). Stellarwave's strip ("capsule") is wider than the reel region:
        there the limits are the wide strip's (about -0.18 .. 1.18 of the reel region)."""
        r = obs.reel
        lo, hi = (-0.2, 1.2) if wide else (-0.02, 1.02)
        if r.fish_found and not (lo <= r.fish_x <= hi):
            r.fish_found = False
        if r.bar_found and (r.bar_left < lo - 0.03 or r.bar_right > hi + 0.03 or r.bar_right <= r.bar_left):
            r.bar_found = False
        if r.ui_present and not (r.fish_found or r.bar_found):
            r.ui_present = False

    # Before the reel, the area it appears in holds other things that never go away: the "Current Bait: ... /
    # Increases Resilience by ..." text under the player (player's screenshot) sits exactly there. Read as a
    # reel, that skipped the cast ("Start does nothing") and ended reels that never were. So outside the reel the
    # area is remembered while casting, and a reel only counts when the area has really changed since.
    GATED_STATES = ("CASTING", "WAITING_FOR_BITE", "SHAKE", "CATCH_CONFIRMED")

    def _reel_gate(self, crop, obs: "Observation", state: str | None, t: float) -> None:
        if crop is None or crop.size == 0 or state is None:
            return
        g = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop, (192, 24),
                       interpolation=cv2.INTER_AREA).astype(np.int16)
        ref = getattr(self, "_reel_ref", None)
        diff = None if ref is None else np.abs(g - ref)
        changed = None if diff is None else float((diff > 25).mean())
        # only what is really the same as before the cast is ignored (static text: ~0 change); a reel - even a
        # dark track on dark water in the test game - changes far more (there: 21% of pixels, average 51)
        same = diff is not None and changed < 0.1 and float(diff.mean()) < 12
        if state in self.GATED_STATES and same and obs.reel.ui_present:
            obs.reel.ui_present = obs.reel.fish_found = obs.reel.bar_found = False
            self.reel_gated = getattr(self, "reel_gated", 0) + 1
        if state == "CASTING" or (state == "WAITING_FOR_BITE" and changed is not None and changed < 0.08
                                  and t - getattr(self, "_reel_ref_t", -1e9) > 1.0):
            self._reel_ref, self._reel_ref_t = g, t  # the area without the reel (follows slow HUD changes)

    def _zodiac(self, frame: Frame, rw: Region):
        """Stellarwave: which sign is next (lit stars in the top row) and where it is on the strip."""
        from fischmacro.vision.zodiac import SIGNS, ZodiacObs, find_on_strip, read_row
        z = ZodiacObs()
        row_r = Region(rw.x, max(0.0, rw.y - 0.24), rw.w, 0.22)
        strip_r = Region(rw.x, max(0.0, rw.y - 0.02), rw.w, rw.h + 0.043)
        row_img, strip = frame.crop(row_r), frame.crop(strip_r)
        if row_img is None or strip is None:
            return z
        row = read_row(row_img)
        if not row.found:
            return z
        z.found, z.lit = True, row.lit
        if row.lit >= 12:
            return z
        z.next_sign = SIGNS[row.lit]
        hit = find_on_strip(strip, row.templates[row.lit])
        if hit is None:
            return z
        cw, ch = frame.client_size
        sx, sy, sw, sh = strip_r.to_rect(cw, ch)
        scale_x = sw / strip.shape[1]
        z.x, z.y = (sx + hit.x * scale_x) / cw, (sy + hit.y * scale_x) / ch
        z.score, z.margin = hit.score, hit.score - hit.second
        return z

    def _lullaby_gauge(self, frame: Frame, reel: Region):
        """Lullaby's half-moon metronome sits on the middle of the reel's top edge."""
        cw, ch = frame.client_size
        cx = (reel.x + reel.w / 2) * cw - frame.origin[0]
        cy = reel.y * ch - frame.origin[1]
        return self.lullaby_gauge.update(frame.image, (cx, cy), ch)

    @staticmethod
    def _tall(region: Region) -> Region:
        """The same columns with rows above and below: only the fish line continues there."""
        return Region(region.x, max(0.0, region.y - 0.6 * region.h), region.w, region.h * 2.2)

    def _refine_fish(self, frame: Frame, obs: Observation, r: Region) -> None:
        """The fish is the strongest thin line crossing the track and continuing past it. MiguRod's '!' marks
        and slash effects fooled the colour/shape fish finder (player recording, 29.5 s); this one checks the
        line continues beyond the track."""
        if not obs.reel.ui_present:
            return
        tall = frame.crop(self._tall(r))
        if tall is None:
            return
        from fischmacro.vision.reel_edges import edge_strength, find_fish
        f = edge_strength(cv2.GaussianBlur(tall, (3, 1), 0))
        ff = find_fish(f, tall.shape[1], tall)
        if ff is None or ff[1] < 0.6:
            return
        rr = obs.reel
        if rr.fish_found and self.profile.minigame.kind != "migu":
            return  # the first finder was right on every normal reel of the recording; marks are a MiguRod thing
        if rr.fish_found and abs(rr.fish_x - ff[0]) > 0.02:
            # keep the first answer if it is a line that also continues past the track (a real fish line);
            # replace it only when it does not (a mark or effect standing on the track)
            w = tall.shape[1]
            c, k = int(rr.fish_x * w), max(4, int(0.015 * w))
            if float(f[max(0, c - k):c + k + 1].max()) >= 0.6 * max(1e-6, float(f[max(0, int(ff[0] * w) - k):
                                                                                 int(ff[0] * w) + k + 1].max())):
                return
        if not rr.fish_found or abs(rr.fish_x - ff[0]) > 0.02:
            rr.fish_found, rr.fish_x, rr.fish_confidence = True, ff[0], max(rr.fish_confidence, ff[1])

    def _capsule_reel(self, frame: Frame, obs: Observation, r: Region, rw: Region) -> None:
        """Stellarwave: a strip of zodiac signs with a bright capsule as the bar (checked on the player's
        recording: bar edges within 16 px, fish within 3 px). Results are put in the normal reel's terms."""
        wide, tall = frame.crop(rw), frame.crop(self._tall(rw))
        if wide is None or tall is None:
            return
        from fischmacro.vision.reel_adaptive import bright_bar
        from fischmacro.vision.reel_edges import edge_strength, find_fish
        w = wide.shape[1]
        ff = find_fish(edge_strength(cv2.GaussianBlur(tall, (3, 1), 0)), w, tall)
        bb = bright_bar(wide, ff[0] if ff else None)
        if bb is None:
            return
        to_reel = lambda f: (rw.x + f * rw.w - r.x) / r.w  # noqa: E731
        rr = obs.reel
        rr.ui_present, rr.bar_found, rr.fish_found = True, True, True
        rr.fish_x, rr.fish_confidence = to_reel(bb.fish_x), bb.fish_confidence
        rr.bar_left, rr.bar_right, rr.bar_confidence = to_reel(bb.bar_left), to_reel(bb.bar_right), bb.bar_confidence

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
