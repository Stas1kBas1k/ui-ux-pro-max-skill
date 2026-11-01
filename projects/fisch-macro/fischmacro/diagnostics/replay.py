"""Replay a recording through the real macro and draw what it sees and does.

    python -m fischmacro.diagnostics.replay FRAMES_DIR --rod stellarwave --fps 30 --out debug_dir

Every frame goes through the same vision engine and fishing state machine as live play; inputs go to a
recording backend instead of the game. Each frame is saved with an overlay:

* green box: reel area; blue: detected bar; red line: detected fish; orange ticks: MiguRod marks;
* yellow ring: Stellarwave's next sign, with the cursor; Lullaby: pendulum angle and lit parts;
* the state, tracking confidence and the inputs sent on that frame.

This is how a failure is split into "did not see it" (detection), "saw it but chose wrong" (decision) or
"chose right but the input did not happen" (input), without a live game.
"""
from __future__ import annotations

import argparse
import csv
import glob
import math
import os
from dataclasses import dataclass, field

import cv2
import numpy as np

from fischmacro.automation.fsm import FishingStateMachine, State
from fischmacro.input.controller import InputController, RecordingBackend
from fischmacro.profiles.rod_presets import apply_preset, find_preset
from fischmacro.profiles.schema import Profile
from fischmacro.vision.engine import VisionEngine
from fischmacro.vision.frame import Frame

ROD_NAMES = {"normal": "", "stellarwave": "Stellarwave Melody", "migu": "MiguRod", "lullaby": "Lullaby",
             "halibut": "Halibut Harpoon"}


@dataclass
class ReplayResult:
    rows: list[dict] = field(default_factory=list)
    inputs: list[tuple[float, str]] = field(default_factory=list)


def profile_for(rod: str) -> Profile:
    p = Profile()
    name = ROD_NAMES.get(rod, rod)
    pre = find_preset(name) if name else None
    if pre is not None:
        apply_preset(p, pre)
    return p


def replay(frames: list[str], rod: str = "normal", fps: float = 30.0, out_dir: str | None = None,
           profile: Profile | None = None) -> ReplayResult:
    p = profile or profile_for(rod)
    backend = RecordingBackend()
    inputs = InputController(backend, click_hold_ms=0, key_hold_ms=0, mouse_nudge=False)
    vision = VisionEngine(p)
    vision.verify_shake = False  # the shake reader runs on its own thread; replays look at the reel
    fsm = FishingStateMachine(p, inputs, emit=lambda *a, **k: None, sleep=lambda s: None)
    fsm.start(0.0)
    fsm._go(State.REELING, 0.0, "replay", force=True)
    res = ReplayResult()
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    for i, path in enumerate(frames):
        img = cv2.imread(path)
        if img is None:
            continue
        H, W = img.shape[:2]
        t = i / fps
        n0 = len(backend.events)
        obs = vision.process(Frame(img, (W, H), timestamp=t), vision.regions_for("REELING"), "REELING")
        fsm.update(obs, t)
        if fsm.state != State.REELING:  # keep reading the whole clip
            fsm._go(State.REELING, t, "replay", force=True)
        sent = [_fmt(e) for e in backend.events[n0:] if e[0] != "move" or True]
        for s in sent:
            res.inputs.append((t, s))
        tr = fsm.tracker.state
        row = {"t": round(t, 3), "fish": obs.reel.fish_x if obs.reel.fish_found else None,
               "bar_l": obs.reel.bar_left if obs.reel.bar_found else None,
               "bar_r": obs.reel.bar_right if obs.reel.bar_found else None, "held": inputs.is_held(),
               "conf": round(tr.confidence, 2), "inputs": " ".join(sent)}
        if obs.zodiac is not None:
            z = obs.zodiac
            row.update(lit=z.lit, next=z.next_sign, zx=round(z.x, 4), zconf=z.confident)
        if p.minigame.kind == "lullaby":
            tm = obs.timing
            row.update(pendulum=round(tm.pointer, 3) if tm.present else None,
                       lit_parts=";".join(f"{a:.2f}-{b:.2f}" for a, b in tm.segments))
        res.rows.append(row)
        if out_dir:
            cv2.imwrite(os.path.join(out_dir, f"{i:04d}.jpg"), draw(img, p, obs, fsm, sent, t))
    if out_dir:
        with open(os.path.join(out_dir, "replay.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=sorted({k for r in res.rows for k in r}))
            w.writeheader()
            w.writerows(res.rows)
    return res


def _fmt(e: tuple) -> str:
    if e[0] == "move":
        return f"move({e[1]},{e[2]})"
    return f"{e[0]}:{e[1]}"


def draw(img: np.ndarray, p: Profile, obs, fsm, sent: list[str], t: float) -> np.ndarray:
    H, W = img.shape[:2]
    out = img.copy()
    r = p.regions["reel"]
    x, y, w, h = r.to_rect(W, H)
    cv2.rectangle(out, (x, y), (x + w, y + h), (0, 200, 0), 1)
    px = lambda f: int(x + f * w)  # noqa: E731
    rr = obs.reel
    if rr.bar_found:
        cv2.rectangle(out, (px(rr.bar_left), y - 6), (px(rr.bar_right), y + h + 6), (255, 160, 0), 3)
    if rr.fish_found:
        cv2.line(out, (px(rr.fish_x), y - 30), (px(rr.fish_x), y + h + 30), (0, 0, 255), 3)
    for m in rr.marks:
        cv2.line(out, (px(m), y - 14), (px(m), y), (0, 140, 255), 4)
    for dr in getattr(obs, "drops", ()):  # falling objects: where they are, and when they land
        cy = int(y - 4 * h + dr.y * 4 * h)
        cv2.circle(out, (px(dr.x), cy), max(6, h // 2), (255, 255, 0), 2)
        if dr.eta is not None:
            cv2.putText(out, f"{dr.eta:.1f}s", (px(dr.x) + 10, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
    z = obs.zodiac
    if z is not None and z.found:
        if z.next_sign:
            c = (int(z.x * W), int(z.y * H))
            cv2.circle(out, c, 34, (0, 255, 255) if z.confident else (0, 120, 120), 3)
        cv2.putText(out, f"stars lit {z.lit} next {z.next_sign} ({z.score:.2f}/{z.margin:.2f})", (20, H - 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    if obs.timing.present and (p.minigame.kind == "lullaby" or obs.timing.source == "gauge"):
        cx, cy = int((r.x + r.w / 2) * W), int(r.y * H)
        rad = int(0.15 * H)
        for a, b in obs.timing.segments:
            cv2.ellipse(out, (cx, cy), (rad + 14, rad + 14), 0, 180 + a * 180, 180 + b * 180, (0, 255, 0), 6)
        ang = math.radians(180 + obs.timing.pointer * 180)
        cv2.line(out, (cx, cy), (int(cx + math.cos(ang) * rad * 1.3), int(cy + math.sin(ang) * rad * 1.3)),
                 (255, 0, 255), 4)
    tr = fsm.tracker.state
    info = f"t={t:5.2f}s  {fsm.state.value}  track {tr.confidence:.0%} {tr.direction}  held={'Y' if fsm.input.is_held() else 'n'}"
    cv2.rectangle(out, (10, H - 60), (W - 10, H - 10), (0, 0, 0), -1)
    cv2.putText(out, info, (20, H - 42), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(out, "inputs: " + (" ".join(sent)[:110] or "-"), (20, H - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (0, 255, 0) if sent else (150, 150, 150), 2)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("frames", help="folder of frames (jpg/png, in order)")
    ap.add_argument("--rod", default="normal", choices=sorted(ROD_NAMES))
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.frames, "*.jpg")) + glob.glob(os.path.join(a.frames, "*.png")))
    res = replay(files, a.rod, a.fps, a.out or None)
    print(f"{len(res.rows)} frames, {len(res.inputs)} inputs")


if __name__ == "__main__":
    main()


def mechanic_summary(obs, kind: str) -> str:
    """One line for the manual test mode: what this mechanic's detector sees right now."""
    if kind == "lullaby":
        t = obs.timing
        if not t.present:
            return "Gauge not found - start a Lullaby catch"
        parts = ", ".join(f"{a:.2f}-{b:.2f}" for a, b in t.segments) or "none"
        return f"Gauge found: pendulum {t.pointer:.2f}, lit parts {parts}"
    if kind == "stellarwave":
        z = obs.zodiac
        if z is None or not z.found:
            return "Zodiac row not found"
        return f"{z.lit} stars lit, next sign {z.next_sign or '?'}" + (" (sure)" if z.confident else " (unsure)")
    if kind == "falling":
        d = [x for x in getattr(obs, "drops", ()) if x.eta is not None]
        return f"{len(d)} falling object(s)" + (f", next lands in {min(x.eta for x in d):.1f} s" if d else "")
    if kind == "migu":
        return f"{len(obs.reel.marks)} slash mark(s) on the track" + (", counter bar seen" if obs.timing.present else "")
    return ""
