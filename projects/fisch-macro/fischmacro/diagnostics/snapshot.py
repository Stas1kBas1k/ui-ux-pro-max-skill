"""Annotated diagnostic snapshots: draw regions + detections onto a frame and save a report."""
from __future__ import annotations

import json
import logging
import platform
import time
import zipfile
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from fischmacro import __version__, paths
from fischmacro.profiles.schema import REGION_LABELS, Profile, to_dict
from fischmacro.vision.engine import Observation
from fischmacro.vision.frame import Frame

log = logging.getLogger(__name__)

REGION_COLORS = {  # BGR
    "reel": (246, 130, 59), "progress": (238, 211, 34), "shake": (237, 58, 124), "cast": (94, 197, 34),
    "catch_popup": (36, 191, 251), "disconnect": (68, 68, 239), "reconnect_button": (180, 180, 180),
}


def annotate(frame: Frame, profile: Profile, obs: Observation | None, scale: float = 1.0) -> np.ndarray:
    """Return a full-client-size BGR image with regions and detections drawn on it."""
    cw, ch = frame.client_size
    canvas = np.zeros((ch, cw, 3), np.uint8)
    ox, oy = frame.origin
    ih, iw = frame.image.shape[:2]
    canvas[oy:oy + ih, ox:ox + iw] = frame.image[: ch - oy, : cw - ox]
    if scale != 1.0:
        canvas = cv2.resize(canvas, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    W, H = canvas.shape[1], canvas.shape[0]
    font = cv2.FONT_HERSHEY_SIMPLEX
    fs = max(0.35, H / 1400)
    for name, region in profile.regions.items():
        if not region.enabled:
            continue
        x, y, w, h = region.to_rect(W, H)
        col = REGION_COLORS.get(name, (200, 200, 200))
        cv2.rectangle(canvas, (x, y), (x + w, y + h), col, 1)
        cv2.putText(canvas, REGION_LABELS.get(name, name), (x + 2, max(10, y - 4)), font, fs, col, 1, cv2.LINE_AA)
    if obs is None:
        return canvas
    r = profile.region("reel")
    rx, ry, rw, rh = r.to_rect(W, H)
    if obs.reel.ui_present:
        x0, x1 = rx + int(obs.reel.bar_left * rw), rx + int(obs.reel.bar_right * rw)
        cv2.rectangle(canvas, (x0, ry - 3), (x1, ry + rh + 3), (255, 255, 255), 2)
    if obs.reel.fish_found:
        fx = rx + int(obs.reel.fish_x * rw)
        cv2.line(canvas, (fx, ry - 10), (fx, ry + rh + 10), (60, 60, 255), 2)
    if obs.reel.ui_present:
        cv2.putText(canvas, f"reel conf {obs.reel.confidence:.2f}", (rx, ry + rh + int(22 * fs * 2)), font, fs,
                    (255, 255, 255), 1, cv2.LINE_AA)
    if obs.progress.present:
        p = profile.region("progress")
        px, py, pw, ph = p.to_rect(W, H)
        cv2.putText(canvas, f"progress {obs.progress.fill:.0%}", (px + pw + 6, py + ph), font, fs, (255, 255, 255), 1, cv2.LINE_AA)
    for t in obs.shake.targets:
        cx, cy = int(t.x * W), int(t.y * H)
        hw, hh = int(t.w * W / 2), int(t.h * H / 2)
        cv2.rectangle(canvas, (cx - hw, cy - hh), (cx + hw, cy + hh), (0, 255, 255), 2)
        cv2.drawMarker(canvas, (cx, cy), (0, 255, 255), cv2.MARKER_CROSS, 14, 2)
    if obs.cast.present:
        c = profile.region("cast")
        x, y, w, h = c.to_rect(W, H)
        ly = y + h - int(obs.cast.fill * h)
        cv2.line(canvas, (x - 6, ly), (x + w + 6, ly), (0, 255, 0), 2)
        cv2.putText(canvas, f"{obs.cast.fill:.0%}", (x + w + 8, ly + 4), font, fs, (0, 255, 0), 1, cv2.LINE_AA)
    if obs.disconnect.detected:
        cv2.putText(canvas, "DISCONNECT DIALOG", (int(W * 0.35), int(H * 0.25)), font, fs * 1.6, (0, 0, 255), 2, cv2.LINE_AA)
    return canvas


def _jsonable(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, tuple):
        return list(o)
    return str(o)


def save_snapshot(frame: Frame, profile: Profile, obs: Observation | None, note: str = "") -> Path:
    """Save raw + annotated PNGs and a JSON report. Returns the folder."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = paths.diagnostics_dir() / f"snapshot-{stamp}"
    i = 1
    while folder.exists():
        folder = paths.diagnostics_dir() / f"snapshot-{stamp}-{i}"
        i += 1
    folder.mkdir(parents=True)
    full = annotate(frame, profile, None)
    cv2.imwrite(str(folder / "raw.png"), full)
    cv2.imwrite(str(folder / "annotated.png"), annotate(frame, profile, obs))
    report = {
        "app_version": __version__, "time": stamp, "note": note, "platform": platform.platform(),
        "client_size": frame.client_size, "screen_origin": frame.screen_origin,
        "observation": asdict(obs) if obs else None, "profile": to_dict(profile),
    }
    (folder / "report.json").write_text(json.dumps(report, indent=2, default=_jsonable), encoding="utf-8")
    log.info("Diagnostic snapshot saved to %s", folder)
    return folder


def export_diagnostics(destination: Path, settings: dict, profile: Profile) -> Path:
    """Zip logs, settings, active profile and recent snapshots. Stays on disk; nothing is uploaded."""
    destination = Path(destination)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(paths.logs_dir().glob("fischmacro*")):
            z.write(f, f"logs/{f.name}")
        z.writestr("settings.json", json.dumps(settings, indent=2))
        z.writestr("profile.json", json.dumps(to_dict(profile), indent=2))
        z.writestr("system.json", json.dumps({"app_version": __version__, "platform": platform.platform(),
                                              "python": platform.python_version()}, indent=2))
        snaps = sorted(paths.diagnostics_dir().glob("snapshot-*"))[-5:]
        for s in snaps:
            for f in s.iterdir():
                z.write(f, f"snapshots/{s.name}/{f.name}")
    return destination
