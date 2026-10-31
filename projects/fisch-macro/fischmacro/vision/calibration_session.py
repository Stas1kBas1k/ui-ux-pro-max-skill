"""Sample-based calibration: many independent looks at the reel, outliers removed, checked before saving.

One look at a few seconds of frames (``autocal.calibrate``) can be fooled by a splash, a menu or the
moment the minigame appears. A session takes a look every half second while the user plays a reel,
keeps going until enough looks agree (how many depends on how much they agree), drops the looks that
disagree with the rest, takes the median, and only then checks the result with the real detectors on
frames that were not used to build it. Nothing is saved unless that check passes, and every failure
says why.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from fischmacro.profiles.schema import Region
from fischmacro.vision.autocal import AutoCalResult

MIN_SAMPLES = 5          # never decide on fewer looks than this
MAX_SAMPLES = 16         # give up after this many looks if they still disagree
SPREAD_OK = 0.006        # median absolute deviation of the region edges (fraction of the window) that is "agreeing"
VALID_RATE = 0.7         # share of check frames on which the detectors must find fish and bar


def _hex(c: str) -> np.ndarray:
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def _median_colour(colours: list[str]) -> str:
    """The sampled colour closest to the per-channel median (a real sample, not a blend)."""
    arr = np.array([_hex(c) for c in colours])
    med = np.median(arr, axis=0)
    return colours[int(np.abs(arr - med).sum(axis=1).argmin())]


@dataclass
class SessionReport:
    state: str = "collecting"     # collecting | ok | failed | cancelled
    samples: int = 0
    found: int = 0                # looks in which the reel was found
    inliers: int = 0
    spread: float | None = None
    validated: str = ""
    reason: str = ""
    result: AutoCalResult | None = None

    def text(self) -> str:
        if self.state == "collecting":
            s = f"Looking... {self.found} good look(s) of {self.samples}"
            if self.spread is not None:
                s += f", agreement {self.spread * 100:.1f}%"
            return s
        if self.state == "ok":
            return f"Calibrated from {self.inliers} agreeing looks; checked: {self.validated}"
        return ("Cancelled" if self.state == "cancelled" else "Calibration failed: ") + self.reason


@dataclass
class CalibrationSession:
    samples: list[AutoCalResult] = field(default_factory=list)
    check_frames: list[np.ndarray] = field(default_factory=list)
    report: SessionReport = field(default_factory=SessionReport)

    @property
    def done(self) -> bool:
        return self.report.state != "collecting"

    def cancel(self) -> None:
        self.report.state, self.report.reason = "cancelled", "cancelled by the user"

    def add(self, res: AutoCalResult, frame: np.ndarray | None) -> None:
        """One independent look (``autocal.calibrate`` on a fresh window of frames)."""
        if self.done:
            return
        r = self.report
        r.samples += 1
        if res.ok:
            self.samples.append(res)
            r.found += 1
            if frame is not None:  # only frames that show a reel can check the result
                self.check_frames.append(frame)
                del self.check_frames[:-12]
        if r.found >= MIN_SAMPLES:
            est, inl, spread = self.estimate()
            r.spread, r.inliers = spread, len(inl)
            # agreeing looks decide sooner; scattered ones need more looks before trusting the median
            needed = MIN_SAMPLES if spread <= SPREAD_OK else MIN_SAMPLES + int(min(8, spread / SPREAD_OK))
            if r.found >= needed and spread <= 3 * SPREAD_OK and len(inl) >= 0.6 * r.found:
                r.result = est
                r.state = "validating"
                return
        if r.samples >= MAX_SAMPLES:
            r.state = "failed"
            if r.found < MIN_SAMPLES:
                r.reason = (f"the reel was found in only {r.found} of {r.samples} looks - keep a reel minigame "
                            "on screen (cast, wait for the bite, play it) and try again, or set the regions by hand")
            else:
                r.reason = (f"the looks disagree about where the reel is (spread {r.spread * 100:.1f}% of the "
                            "window) - something on screen moves like the reel. Close menus and try again, or "
                            "set the regions by hand")

    def estimate(self) -> tuple[AutoCalResult, list[AutoCalResult], float]:
        """Median over looks after dropping outliers (more than 3 MADs from the median edge)."""
        edges = np.array([[s.reel.x, s.reel.y, s.reel.x + s.reel.w, s.reel.y + s.reel.h] for s in self.samples])
        med = np.median(edges, axis=0)
        mad = np.median(np.abs(edges - med), axis=0)
        limit = np.maximum(3 * 1.4826 * mad, 0.01)
        keep = (np.abs(edges - med) <= limit).all(axis=1)
        inl = [s for s, k in zip(self.samples, keep) if k]
        e = np.median(edges[keep], axis=0) if keep.any() else med
        # the worst edge counts: a reel that is steady in height but jumps sideways does not agree
        spread = float(np.median(np.abs(edges[keep] - e), axis=0).max()) if keep.any() else 1.0
        out = AutoCalResult(reel=Region(float(e[0]), float(e[1]), float(e[2] - e[0]), float(e[3] - e[1])))
        for attr in ("bar_color", "fish_color", "progress_color", "cast_color"):
            vals = [getattr(s, attr) for s in inl if getattr(s, attr)]
            if vals:
                setattr(out, attr, _median_colour(vals))
        progs = [s.progress for s in inl if s.progress is not None]
        if len(progs) >= max(2, len(inl) // 2):
            p = np.median([[g.x, g.y, g.w, g.h] for g in progs], axis=0)
            out.progress = Region(*map(float, p))
        out.confidence = float(np.median([s.confidence for s in inl])) if inl else 0.0
        out.notes = [f"{len(inl)} of {len(self.samples)} looks agree"]
        return out, inl, spread

    def validate(self, profile) -> bool:
        """Check the estimate with the real detectors on the saved frames. Sets the final state."""
        import copy

        from fischmacro.vision.autocal import apply_result
        from fischmacro.vision.engine import VisionEngine
        from fischmacro.vision.frame import Frame

        r = self.report
        if r.state != "validating" or r.result is None:
            return False
        frames = self.check_frames
        trial = copy.deepcopy(profile)
        apply_result(trial, r.result)
        engine = VisionEngine(trial)
        good = 0
        for img in frames:
            rr = engine.process(Frame(img, (img.shape[1], img.shape[0])), ("reel",)).reel
            good += bool(rr.fish_found and rr.bar_found and 0.01 < rr.fish_x < 0.99)
        need = max(3, int(np.ceil(VALID_RATE * len(frames))))
        r.validated = f"fish and bar found in {good} of {len(frames)} frames"
        if len(frames) >= 3 and good >= need:
            r.state = "ok"
            return True
        r.state = "failed"
        r.reason = (f"with these settings the fish and bar were found in only {good} of {len(frames)} frames "
                    f"(need {need}). Nothing was saved. Try again during a reel, or set the regions by hand")
        return False
