"""What happened during each reel, in numbers, plus an optional frame-by-frame recording.

Player: "the tracking looks like it has a massive delay", "Stellarwave gets worse after a few catches". Logs
said only "Fish escaped in 7.3s". Now every reel ends with one line that shows where the time and the misses
go - frame rate, vision time, the delay from the screen grab to the input decision, how often the fish and
the bar were seen, how often the macro fell back to fish-only steering, how far the bar was from the fish, and
for Stellarwave how often the sign row was read and the next sign found, with taps and picks.

With Settings > Diagnostics > Record reels, the reel area of every frame is also saved (JPEG, full
resolution, at most 40 per second) with the decisions made on it, into ``data/recordings`` (last 6 reels).
The diagnostics zip carries the newest 2, so a reel can be replayed through the real code later.
"""
from __future__ import annotations

import json
import logging
import queue
import shutil
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from fischmacro import paths

log = logging.getLogger(__name__)


def _pct(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


class ReelReport:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.t0: float | None = None

    def add(self, row: dict) -> None:
        if self.t0 is None:
            self.t0 = row["t"]
        self.rows.append(row)

    def summary(self, kind: str) -> str:
        r = self.rows
        n = len(r)
        if n < 5:
            return ""
        span = max(1e-3, r[-1]["t"] - r[0]["t"])
        fps = (n - 1) / span
        vis = [x["vision_ms"] for x in r]
        lat = [x["delay_ms"] for x in r if x["delay_ms"] is not None]
        share = lambda key: sum(1 for x in r if x.get(key)) / n  # noqa: E731
        steer = [x for x in r if x.get("mode") == "track"]
        inside = [x for x in steer if x["bar_l"] <= x["fish"] <= x["bar_r"]]
        off = [abs(x["fish"] - (x["bar_l"] + x["bar_r"]) / 2) / max(1e-3, x["bar_r"] - x["bar_l"]) for x in steer]
        line = (f"Reel report: {n} frames at {fps:.0f} fps; vision {_pct(vis, .5):.0f} ms (p95 {_pct(vis, .95):.0f}), "
                f"screen-to-decision {_pct(lat, .5):.0f} ms (p95 {_pct(lat, .95):.0f}); fish seen {share('fish_seen'):.0%}, "
                f"bar seen {share('bar_seen'):.0%}; steering: tracked {len(steer) / n:.0%}, "
                f"fish only {sum(1 for x in r if x.get('mode') == 'fish only') / n:.0%}, "
                f"released (unsure) {sum(1 for x in r if x.get('mode') == 'released') / n:.0%}")
        if steer:
            line += f"; fish inside the bar {len(inside) / len(steer):.0%}, off-centre {np.mean(off):.2f} bar widths"
        if kind == "stellarwave":
            z = [x for x in r if "z_found" in x]
            if z:
                line += (f"; Stellarwave: sign row read {sum(x['z_found'] for x in z) / len(z):.0%}, next sign found "
                         f"{sum(x['z_located'] for x in z) / len(z):.0%} (sure {sum(x['z_sure'] for x in z) / len(z):.0%}), "
                         f"signs lit at the end {max(x['z_lit'] for x in z)}")
        return line


class ReelRecorder:
    """Writes frames in a background thread so the frame loop never waits on the disk."""

    KEEP = 6
    MAX_FPS = 40

    def __init__(self) -> None:
        self.folder: Path | None = None
        self.q: queue.Queue = queue.Queue(maxsize=240)
        self.n = 0
        self._last = -1e9
        self.dropped = 0
        threading.Thread(target=self._writer, name="reel-recorder", daemon=True).start()

    @staticmethod
    def root() -> Path:
        d = paths.data_dir() / "recordings"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def begin(self, meta: dict) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.folder = self.root() / f"reel-{stamp}"
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
        self.n, self._last = 0, -1e9
        olds = sorted(self.root().glob("reel-*"))[:-self.KEEP]
        for o in olds:
            shutil.rmtree(o, ignore_errors=True)

    def add(self, image: np.ndarray | None, row: dict) -> None:
        if self.folder is None:
            return
        if image is not None and row["t"] - self._last >= 1.0 / self.MAX_FPS:
            self._last = row["t"]
            self.n += 1
            row = dict(row, image=f"{self.n:05d}.jpg")
            try:
                self.q.put_nowait((self.folder, row, image.copy()))
            except queue.Full:
                self.dropped += 1  # the disk is behind: skip this picture rather than slow the reel down
        else:
            try:
                self.q.put_nowait((self.folder, row, None))
            except queue.Full:
                self.dropped += 1

    def end(self) -> None:
        self.folder = None

    def _writer(self) -> None:
        while True:
            folder, row, image = self.q.get()
            try:
                if image is not None:
                    cv2.imwrite(str(folder / row["image"]), image, [cv2.IMWRITE_JPEG_QUALITY, 88])
                with open(folder / "frames.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, default=float) + "\n")
            except Exception:  # noqa: BLE001
                log.debug("recording write failed", exc_info=True)
