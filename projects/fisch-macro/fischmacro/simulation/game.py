"""A simulated Fisch-like fishing game used for test mode and automated tests.

It renders synthetic frames in the default calibrated layout and reacts to the
same mouse/keyboard events the real game would get, so the full pipeline
(capture -> vision -> state machine -> input) can run without Roblox. It is a
model of the mechanics, not a copy of the game: real-game tuning still needs
live testing.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from fischmacro.input.controller import InputBackend
from fischmacro.profiles.schema import DEFAULT_REGIONS, DetectionConfig, Region
from fischmacro.vision.frame import hex_to_bgr


@dataclass
class SimStats:
    casts: int = 0
    perfect_casts: int = 0
    catches: int = 0
    failures: int = 0
    escaped: int = 0
    shake_hits: int = 0
    misclicks: int = 0


class SimulatedFischGame:
    def __init__(self, width: int = 1280, height: int = 720, seed: int | None = None,
                 difficulty: float = 0.4, noise: float = 0.0, regions: dict[str, Region] | None = None,
                 colors: DetectionConfig | None = None):
        self.width, self.height = width, height
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)
        self.difficulty = difficulty
        # Rod physics: bar acceleration while held / released. Hover duty = release / (hold + release).
        self.accel_hold = 2.4
        self.accel_release = 2.4
        self.noise = noise
        self.regions = regions or DEFAULT_REGIONS
        self.colors = colors or DetectionConfig()
        self.lock = threading.RLock()
        self.t = 0.0
        self.state = "idle"
        self.state_t = 0.0
        self.mouse_held = False
        self.cursor = (width // 2, height // 2)
        self.nav_mode = False
        self.stats = SimStats()
        self._real_last: float | None = None
        self._bg = self._make_background()
        # per-state data
        self.power = 0.0
        self.bite_at = 0.0
        self.shakes_needed = 0
        self.shake_button: tuple[float, float] | None = None
        self.next_button_at = 0.0
        self.bar_x = 0.4
        self.bar_v = 0.0
        self.bar_w = 0.25
        self.fish_x = 0.5
        self.fish_target = 0.5
        self.fish_retarget_at = 0.0
        self.progress = 0.3
        self.last_result = ""

    # ------------------------------------------------------------------ helpers
    def _rect(self, name: str) -> tuple[int, int, int, int]:
        return self.regions[name].to_rect(self.width, self.height)

    def _set(self, state: str) -> None:
        self.state = state
        self.state_t = self.t

    def _make_background(self) -> np.ndarray:
        h, w = self.height, self.width
        img = np.zeros((h, w, 3), np.uint8)
        horizon = int(h * 0.42)
        sky_top, sky_bot = np.array([215, 170, 110]), np.array([235, 205, 160])
        water_top, water_bot = np.array([130, 95, 40]), np.array([90, 60, 20])
        for y in range(h):
            if y < horizon:
                c = sky_top + (sky_bot - sky_top) * (y / horizon)
            else:
                c = water_top + (water_bot - water_top) * ((y - horizon) / (h - horizon))
            img[y, :] = c
        # A dock and a few islands for visual texture (deliberately not matching detector colours).
        cv2.rectangle(img, (0, int(h * 0.62)), (int(w * 0.62), int(h * 0.70)), (40, 75, 110), -1)
        cv2.ellipse(img, (int(w * 0.18), horizon), (int(w * 0.12), int(h * 0.05)), 0, 180, 360, (60, 120, 70), -1)
        cv2.ellipse(img, (int(w * 0.82), horizon), (int(w * 0.09), int(h * 0.04)), 0, 180, 360, (55, 110, 65), -1)
        # Large bright cloud: bigger than any shake button so the area filter must reject it.
        cv2.ellipse(img, (int(w * 0.32), int(h * 0.20)), (int(w * 0.16), int(h * 0.07)), 0, 0, 360, (242, 242, 242), -1)
        return img

    # ------------------------------------------------------------------ input
    def mouse_down(self) -> None:
        with self.lock:
            if self.mouse_held:
                return
            self.mouse_held = True
            if self.state == "idle":
                self._set("casting")
                self.stats.casts += 1
            elif self.state == "shake" and self.shake_button is not None:
                bx, by = self.shake_button
                bw, bh = self._button_size()
                cx, cy = self.cursor
                if abs(cx / self.width - bx) <= bw / 2 and abs(cy / self.height - by) <= bh / 2:
                    self._shake_hit()
                else:
                    self.stats.misclicks += 1
            elif self.state == "waiting":
                self._set("idle")  # clicking while the line is out reels it back in
            elif self.state == "disconnected":
                x, y, w, h = self._rect("reconnect_button")
                cx, cy = self.cursor
                if x <= cx <= x + w and y <= cy <= y + h:
                    self._set("reconnecting")

    def mouse_up(self) -> None:
        with self.lock:
            if not self.mouse_held:
                return
            self.mouse_held = False
            if self.state == "casting":
                self.power = self._power()
                if self.power >= 0.95:
                    self.stats.perfect_casts += 1
                self._set("waiting")
                base = self.rng.uniform(1.0, 3.5)
                self.bite_at = self.t + (base * 0.6 if self.power >= 0.95 else base)

    def move(self, x: int, y: int) -> None:
        with self.lock:
            self.cursor = (int(x), int(y))

    def key(self, key: str) -> None:
        with self.lock:
            k = key.lower()
            if k in ("\\", "backslash"):
                self.nav_mode = not self.nav_mode
            elif k in ("enter", "return") and self.nav_mode and self.state == "shake" and self.shake_button:
                self._shake_hit()

    def disconnect(self) -> None:
        with self.lock:
            self.mouse_held = False
            self._set("disconnected")

    # ------------------------------------------------------------------ mechanics
    def _button_size(self) -> tuple[float, float]:
        return 0.06, 0.075

    def _power(self) -> float:
        phase = ((self.t - self.state_t) / 1.0) % 2.0
        return 1.0 - abs(phase - 1.0)

    def _spawn_button(self) -> None:
        r = self.regions["shake"]
        bw, bh = self._button_size()
        self.shake_button = (self.rng.uniform(r.x + bw, r.x + r.w - bw), self.rng.uniform(r.y + bh, r.y + r.h - bh))

    def _shake_hit(self) -> None:
        self.stats.shake_hits += 1
        self.shakes_needed -= 1
        self.shake_button = None
        if self.shakes_needed <= 0:
            self._start_reel()
        else:
            self.next_button_at = self.t + 0.15

    def _start_reel(self) -> None:
        self._set("reel")
        self.bar_w = 0.30 - 0.12 * self.difficulty
        self.bar_x = 0.5 - self.bar_w / 2
        self.bar_v = 0.0
        self.fish_x = self.rng.uniform(0.3, 0.7)
        self.fish_target = self.fish_x
        self.fish_retarget_at = self.t + 0.5
        self.progress = 0.3

    def _finish(self, success: bool) -> None:
        self.mouse_held = self.mouse_held  # input state is untouched
        if success:
            self.stats.catches += 1
            self.last_result = "caught"
        else:
            self.stats.failures += 1
            self.last_result = "lost"
        self._set("result")

    def step(self, dt: float) -> None:
        with self.lock:
            self.t += dt
            s = self.state
            if s == "waiting" and self.t >= self.bite_at:
                self._set("shake")
                self.shakes_needed = self.rng.randint(2, 5)
                self.next_button_at = self.t + 0.1
            elif s == "shake":
                if self.shake_button is None and self.t >= self.next_button_at:
                    self._spawn_button()
                if self.t - self.state_t > 15.0:
                    self.stats.escaped += 1
                    self.shake_button = None
                    self._set("idle")
            elif s == "reel":
                self._reel_step(dt)
            elif s == "result" and self.t - self.state_t > 1.2:
                self._set("idle")
            elif s == "reconnecting" and self.t - self.state_t > 2.0:
                self._set("idle")

    def _reel_step(self, dt: float) -> None:
        accel = self.accel_hold if self.mouse_held else -self.accel_release
        self.bar_v += accel * dt
        self.bar_v *= max(0.0, 1.0 - 1.2 * dt)
        self.bar_x += self.bar_v * dt
        hi = 1.0 - self.bar_w
        if self.bar_x < 0:
            self.bar_x, self.bar_v = 0.0, -self.bar_v * 0.25
        elif self.bar_x > hi:
            self.bar_x, self.bar_v = hi, -self.bar_v * 0.25
        if self.t >= self.fish_retarget_at:
            self.fish_target = self.rng.uniform(0.04, 0.96)
            self.fish_retarget_at = self.t + self.rng.uniform(0.5, 1.6) * (1.0 - 0.4 * self.difficulty)
        speed = 0.22 + 0.45 * self.difficulty
        delta = self.fish_target - self.fish_x
        self.fish_x += max(-speed * dt, min(speed * dt, delta))
        inside = self.bar_x <= self.fish_x <= self.bar_x + self.bar_w
        self.progress += (0.30 if inside else -0.20) * dt
        if self.progress >= 1.0:
            self.progress = 1.0
            self._finish(True)
        elif self.progress <= 0.0:
            self.progress = 0.0
            self._finish(False)

    def advance_realtime(self, max_dt: float = 0.1) -> None:
        now = time.monotonic()
        if self._real_last is None:
            self._real_last = now
            return
        dt = min(max_dt, now - self._real_last)
        self._real_last = now
        while dt > 1e-6:
            sub = min(dt, 1 / 120)
            self.step(sub)
            dt -= sub

    # ------------------------------------------------------------------ rendering
    def render(self) -> np.ndarray:
        with self.lock:
            img = self._bg.copy()
            h, w = self.height, self.width
            # animated water lines keep frames from being identical
            for i in range(6):
                y = int(h * (0.48 + i * 0.07))
                x = int((self.t * 40 + i * 97) % w)
                cv2.line(img, (x, y), (min(w, x + int(w * 0.08)), y), (150, 115, 60), 2)
            cv2.rectangle(img, (int(w * 0.485), int(h * 0.50)), (int(w * 0.515), int(h * 0.62)), (60, 90, 140), -1)
            cv2.circle(img, (int(w * 0.5), int(h * 0.48)), int(h * 0.025), (120, 160, 210), -1)
            c = self.colors
            s = self.state
            if s == "casting":
                x, y, rw, rh = self._rect("cast")
                cv2.rectangle(img, (x, y), (x + rw, y + rh), (30, 30, 30), -1)
                fill = int(rh * self._power())
                if fill > 0:
                    cv2.rectangle(img, (x + 2, y + rh - fill), (x + rw - 2, y + rh - 1), hex_to_bgr(c.cast_color), -1)
            elif s == "shake" and self.shake_button is not None:
                bx, by = self.shake_button
                bw, bh = self._button_size()
                p0 = (int((bx - bw / 2) * w), int((by - bh / 2) * h))
                p1 = (int((bx + bw / 2) * w), int((by + bh / 2) * h))
                col = hex_to_bgr(c.shake_color)
                rad = max(2, (p1[1] - p0[1]) // 3)
                cv2.rectangle(img, (p0[0] + rad, p0[1]), (p1[0] - rad, p1[1]), col, -1)
                cv2.rectangle(img, (p0[0], p0[1] + rad), (p1[0], p1[1] - rad), col, -1)
                for cx, cy in ((p0[0] + rad, p0[1] + rad), (p1[0] - rad, p0[1] + rad),
                               (p0[0] + rad, p1[1] - rad), (p1[0] - rad, p1[1] - rad)):
                    cv2.circle(img, (cx, cy), rad, col, -1)
                fs = max(0.3, (p1[1] - p0[1]) / 70)
                cv2.putText(img, "SHAKE", (p0[0] + int(0.12 * (p1[0] - p0[0])), (p0[1] + p1[1]) // 2 + int(8 * fs)),
                            cv2.FONT_HERSHEY_SIMPLEX, fs, (40, 40, 40), max(1, int(2 * fs)), cv2.LINE_AA)
            elif s == "reel":
                self._render_reel(img)
            elif s == "result" and self.last_result == "caught":
                x, y, rw, rh = self._rect("catch_popup")
                cv2.putText(img, "Caught a fish!", (x + rw // 8, y + rh // 2), cv2.FONT_HERSHEY_DUPLEX,
                            max(0.5, rh / 70), (60, 200, 255), 2, cv2.LINE_AA)
            elif s in ("disconnected", "reconnecting"):
                img = (img * 0.35).astype(np.uint8)
                x, y, rw, rh = self._rect("disconnect")
                cv2.rectangle(img, (x + rw // 20, y + rh // 20), (x + rw - rw // 20, y + rh - rh // 20),
                              hex_to_bgr(c.dialog_color), -1)
                cv2.putText(img, "Disconnected", (x + rw // 6, y + rh // 4), cv2.FONT_HERSHEY_SIMPLEX,
                            max(0.5, rh / 300), (235, 235, 235), 2, cv2.LINE_AA)
                bx, by, bw, bh = self._rect("reconnect_button")
                cv2.rectangle(img, (bx, by), (bx + bw, by + bh), (230, 230, 230), -1)
                cv2.putText(img, "Reconnect", (bx + bw // 10, by + int(bh * 0.7)), cv2.FONT_HERSHEY_SIMPLEX,
                            max(0.35, bh / 70), (40, 40, 40), 1, cv2.LINE_AA)
            if self.noise > 0:
                n = self.np_rng.normal(0, self.noise, img.shape)
                img = np.clip(img.astype(np.float32) + n, 0, 255).astype(np.uint8)
            return img

    def _render_reel(self, img: np.ndarray) -> None:
        c = self.colors
        x, y, rw, rh = self._rect("reel")
        cv2.rectangle(img, (x - 3, y - 3), (x + rw + 3, y + rh + 3), (20, 20, 20), -1)
        cv2.rectangle(img, (x, y), (x + rw, y + rh), (45, 38, 34), -1)
        inset = max(1, rh // 10)
        bx0 = x + int(self.bar_x * rw)
        bx1 = x + int((self.bar_x + self.bar_w) * rw)
        cv2.rectangle(img, (bx0, y + inset), (bx1, y + rh - inset), hex_to_bgr(c.bar_color), -1)
        fw = max(3, int(0.022 * rw))
        fx = x + int(self.fish_x * rw)
        cv2.rectangle(img, (fx - fw // 2, y + inset * 2), (fx + fw // 2, y + rh - inset * 2), hex_to_bgr(c.fish_color), -1)
        px, py, pw, ph = self._rect("progress")
        cv2.rectangle(img, (px, py), (px + pw, py + ph), (40, 40, 40), -1)
        fill = int(pw * self.progress)
        if fill > 0:
            cv2.rectangle(img, (px, py), (px + fill, py + ph), hex_to_bgr(c.progress_color), -1)

    # ------------------------------------------------------------------ ground truth (tests)
    def truth(self) -> dict:
        with self.lock:
            return {"state": self.state, "fish_x": self.fish_x, "bar_left": self.bar_x,
                    "bar_right": self.bar_x + self.bar_w, "progress": self.progress,
                    "button": self.shake_button, "power": self._power() if self.state == "casting" else 0.0}


class SimulatedInputBackend(InputBackend):
    """Routes InputController events into the simulated game instead of the OS."""

    name = "simulation"

    def __init__(self, game: SimulatedFischGame):
        self.game = game

    def move(self, x, y):
        self.game.move(x, y)

    def button(self, down, button="left"):
        if button != "left":
            return
        (self.game.mouse_down if down else self.game.mouse_up)()

    def key(self, down, key):
        if down:
            self.game.key(key)
