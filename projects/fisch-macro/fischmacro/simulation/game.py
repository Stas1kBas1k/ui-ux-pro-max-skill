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
    mini_hits: int = 0
    mini_misses: int = 0
    mode_presses: int = 0


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
        # Rod stats: None = derive bar width from difficulty. Low resilience = fast progress drain.
        self.bar_width: float | None = None
        self.progress_gain = 0.30
        self.progress_drain = 0.20
        # Fancy rod skin (see random_skin); None = the plain default look
        self.skin: dict | None = None
        # Rod minigame on top of the reel: None | "lullaby" | "stellarwave" | "targets"
        self.rod_minigame: str | None = None
        self.mini_action = "click"     # or a key name
        self.mini_period = 1.4         # lullaby pendulum period (s)
        self.input_latency = 0.04      # a click lands this long after the frame it was decided on
        self._pending_clicks: list[float] = []
        self._segments: list[tuple[float, float]] = []
        self._signs: list[tuple[str, float, float]] = []
        self._target_sign = ""
        self._targets: list[tuple[float, float]] = []
        # Items / inventory / appraiser, for routine tests
        self.inventory_items = ["Luck Potion", "Aurora Totem", "Astral Activator", "Enchant Relic"]
        self.slots = {"1": "Rod"}
        self.inventory_open = False
        self.search_text = ""
        self.search_focused = False
        self.equipped = "Rod"
        self.items_used: dict[str, int] = {}
        self.appraise_ui = False
        self.appraise_result = ""
        self.mutations = ["Normal", "Albino", "Shiny", "Normal", "Darkened", "Sparkling"]
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
    def _inside(self, cx, cy, w=0.12, h=0.03) -> bool:
        x, y = self.cursor[0] / self.width, self.cursor[1] / self.height
        return abs(x - cx) <= w and abs(y - cy) <= h

    def _matches(self) -> list[str]:
        q = self.search_text.lower()
        return [i for i in self.inventory_items if q and q in i.lower()]

    def mouse_down(self) -> None:
        with self.lock:
            if self.mouse_held:
                return
            self.mouse_held = True
            if self.inventory_open:
                if self._inside(0.5, 0.25):
                    self.search_focused = True
                elif self._inside(0.5, 0.35) and self._matches():
                    self.equipped = self._matches()[0]
                return
            if self.appraise_ui and self._inside(0.8, 0.6, 0.06, 0.03):
                self.appraise_result = self.rng.choice(self.mutations)
                return
            if self.state == "idle" and self.equipped != "Rod":
                self.items_used[self.equipped] = self.items_used.get(self.equipped, 0) + 1
                return
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
            elif self.state == "reel" and self.mini_action == "click":
                if self.rod_minigame == "lullaby" and self.input_latency > 0:
                    self._pending_clicks.append(self.t + self.input_latency)  # lands a little later, as in game
                else:
                    self._mini_action()
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
            if k == "`":
                self.inventory_open = not self.inventory_open
                self.search_text, self.search_focused = "", False
                return
            if self.inventory_open and self.search_focused and len(key) == 1:
                self.search_text += key
                return
            if k in self.slots and self.state in ("idle", "result"):
                self.equipped = self.slots[k]
                return
            if k in ("\\", "backslash"):
                self.nav_mode = not self.nav_mode
            elif k in ("enter", "return") and self.nav_mode and self.state == "shake" and self.shake_button:
                self._shake_hit()
            elif k == "q" and self.state == "reel":
                self.stats.mode_presses += 1
            elif self.state == "reel" and self.rod_minigame and k == self.mini_action:
                if self.rod_minigame == "lullaby" and self.input_latency > 0:
                    self._pending_clicks.append(self.t + self.input_latency)
                else:
                    self._mini_action()

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
        self.bar_w = self.bar_width if self.bar_width else 0.30 - 0.12 * self.difficulty
        self.bar_x = 0.5 - self.bar_w / 2
        self.bar_v = 0.0
        self.fish_x = self.rng.uniform(0.3, 0.7)
        self.fish_target = self.fish_x
        self.fish_retarget_at = self.t + 0.5
        self.progress = 0.3
        if self.rod_minigame == "lullaby":
            self._new_segments()
        elif self.rod_minigame == "stellarwave":
            self._new_signs()
        elif self.rod_minigame == "targets":
            self._new_targets()

    # ------------------------------------------------------------------ rod minigames
    def _new_segments(self) -> None:
        n = self.rng.randint(1, 3)
        self._segments = []
        for _ in range(n):
            w = self.rng.uniform(0.06, 0.12)
            a = self.rng.uniform(0.05, 0.95 - w)
            self._segments.append((a, a + w))

    def _pointer(self, ahead: float = 0.0) -> float:
        import math
        return 0.5 + 0.47 * math.sin(2 * math.pi * (self.t + ahead - self.state_t) / self.mini_period)

    _SIGNS = ("circle", "triangle", "square", "cross")

    def _new_signs(self) -> None:
        r = self.regions["mini"]
        names = list(self._SIGNS)
        self.rng.shuffle(names)
        self._signs = [(n, r.x + r.w * (i + 0.5) / 4, r.y + r.h / 2) for i, n in enumerate(names)]
        self._target_sign = self.rng.choice(names)

    def _new_targets(self) -> None:
        r = self.regions["mini"]
        self._targets = [(self.rng.uniform(r.x + 0.02, r.x + r.w - 0.02), self.rng.uniform(r.y + 0.02, r.y + r.h - 0.02))
                         for _ in range(self.rng.randint(1, 3))]

    def _mini_action(self) -> None:
        kind = self.rod_minigame
        if kind == "lullaby":
            if self.t - self.state_t < 1.2:
                return  # in game, clicks in the first 1.2 s of a reel count for nothing
            p = self._pointer()
            if any(a <= p <= b for a, b in self._segments):
                self.stats.mini_hits += 1
                self._new_segments()
            else:
                self.stats.mini_misses += 1
                self.progress = max(0.0, self.progress - 0.05)  # as in game: a miss costs 5% progress
        elif kind in ("stellarwave", "targets"):
            cx, cy = self.cursor[0] / self.width, self.cursor[1] / self.height
            if kind == "stellarwave":
                hit = [n for n, x, y in self._signs if abs(cx - x) < 0.035 and abs(cy - y) < 0.05]
                if not hit:
                    return  # clicks outside the wheel do nothing
                if hit[0] == self._target_sign:
                    self.stats.mini_hits += 1
                    self._new_signs()
                else:
                    self.stats.mini_misses += 1
            else:
                for t in self._targets:
                    if abs(cx - t[0]) < 0.02 and abs(cy - t[1]) < 0.03:
                        self._targets.remove(t)
                        self.stats.mini_hits += 1
                        if not self._targets:
                            self._new_targets()
                        return

    def _render_mini(self, img: np.ndarray) -> None:
        kind = self.rod_minigame
        if kind == "lullaby":
            x, y, w, h = self._rect("mini")
            ty0, ty1 = y + int(h * 0.35), y + int(h * 0.65)
            k = self.skin or {}
            cv2.rectangle(img, (x, ty0), (x + w, ty1), k.get("track_top", (60, 40, 40)), -1)
            for a, b in self._segments:
                cv2.rectangle(img, (x + int(a * w), ty0), (x + int(b * w), ty1), k.get("lit", (74, 213, 255)), -1)
            px = x + int(self._pointer() * w)
            cv2.rectangle(img, (px - 2, y), (px + 2, y + h), k.get("pointer", (255, 255, 255)), -1)
        elif kind == "stellarwave":
            self._draw_sign(img, self._target_sign, self.regions["mini_target"].center(), 0.035)
            for n, sx, sy in self._signs:
                self._draw_sign(img, n, (sx, sy), 0.03)
        elif kind == "targets":
            for tx, ty in self._targets:
                cv2.circle(img, (int(tx * self.width), int(ty * self.height)), max(4, int(self.height * 0.012)),
                           (48, 59, 255), -1)

    def _draw_sign(self, img, name, centre, size) -> None:
        cx, cy = int(centre[0] * self.width), int(centre[1] * self.height)
        r = int(size * self.height)
        col, t = (255, 255, 255), max(2, r // 6)
        if name == "circle":
            cv2.circle(img, (cx, cy), r, col, t)
        elif name == "square":
            cv2.rectangle(img, (cx - r, cy - r), (cx + r, cy + r), col, t)
        elif name == "triangle":
            pts = np.array([(cx, cy - r), (cx - r, cy + r), (cx + r, cy + r)], np.int32)
            cv2.polylines(img, [pts], True, col, t)
        else:
            cv2.line(img, (cx - r, cy - r), (cx + r, cy + r), col, t)
            cv2.line(img, (cx - r, cy + r), (cx + r, cy - r), col, t)

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
            while self._pending_clicks and self._pending_clicks[0] <= self.t:
                self._pending_clicks.pop(0)
                if self.state == "reel":
                    self._mini_action()
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
        self.progress += (self.progress_gain if inside else -self.progress_drain) * dt
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
                self._render_mini(img)
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
            if self.inventory_open:
                x0, y0, x1, y1 = int(w * 0.35), int(h * 0.15), int(w * 0.65), int(h * 0.55)
                cv2.rectangle(img, (x0, y0), (x1, y1), (40, 36, 34), -1)
                cv2.rectangle(img, (int(w * 0.38), int(h * 0.22)), (int(w * 0.62), int(h * 0.28)), (70, 66, 64), -1)
                cv2.putText(img, self.search_text or "Search...", (int(w * 0.39), int(h * 0.265)),
                            cv2.FONT_HERSHEY_SIMPLEX, h / 1100, (230, 230, 230), 1, cv2.LINE_AA)
                for i, item in enumerate(self._matches()[:3]):
                    cv2.putText(img, item, (int(w * 0.39), int(h * (0.365 + i * 0.06))), cv2.FONT_HERSHEY_SIMPLEX,
                                h / 1100, (230, 230, 230), 1, cv2.LINE_AA)
            if self.appraise_ui:
                bx, by = int(w * 0.8), int(h * 0.6)
                cv2.rectangle(img, (bx - int(w * 0.06), by - int(h * 0.03)), (bx + int(w * 0.06), by + int(h * 0.03)),
                              (60, 140, 60), -1)
                cv2.putText(img, "Appraise", (bx - int(w * 0.045), by + int(h * 0.01)), cv2.FONT_HERSHEY_SIMPLEX,
                            h / 1000, (255, 255, 255), 2, cv2.LINE_AA)
                if self.appraise_result:
                    cv2.putText(img, f"Result: {self.appraise_result}", (bx - int(w * 0.08), by + int(h * 0.08)),
                                cv2.FONT_HERSHEY_SIMPLEX, h / 1000, (255, 255, 255), 2, cv2.LINE_AA)
            if self.noise > 0:
                n = self.np_rng.normal(0, self.noise, img.shape)
                img = np.clip(img.astype(np.float32) + n, 0, 255).astype(np.uint8)
            return img

    def _render_skinned_reel(self, img: np.ndarray) -> None:
        """Skinned reel like real rod skins: ornament frame at the ends, vertical gradient track,
        see-through bar, fish drawn as a thin marker with an outline."""
        k = self.skin
        x, y, rw, rh = self._rect("reel")
        orn = int(rw * k["ornament"])
        tx0, tx1 = x + orn, x + rw - orn
        # frame / ornaments (static decoration)
        cv2.rectangle(img, (x, y - 4), (x + rw, y + rh + 4), k["frame"], -1)
        if orn:
            for cx in (x + orn // 2, x + rw - orn // 2):
                cv2.circle(img, (cx, y + rh // 2), max(4, rh // 2 + 3), k["ornament_col"], -1)
                cv2.circle(img, (cx, y + rh // 2), max(2, rh // 4), k["frame"], -1)
        top, bot = np.array(k["track_top"], np.float32), np.array(k["track_bot"], np.float32)
        for i in range(rh):
            col = top + (bot - top) * (i / max(1, rh - 1))
            img[y + i, tx0:tx1] = col.astype(np.uint8)
        cv2.rectangle(img, (tx0, y), (tx1, y + rh), k["outline"], 1)
        tw = tx1 - tx0
        bx0 = tx0 + int(self.bar_x * tw)
        bx1 = tx0 + int((self.bar_x + self.bar_w) * tw)
        a = k["bar_alpha"]
        seg = img[y + 1:y + rh - 1, bx0:bx1].astype(np.float32)
        img[y + 1:y + rh - 1, bx0:bx1] = (seg * (1 - a) + np.array(k["bar"], np.float32) * a).astype(np.uint8)
        fx = tx0 + int(self.fish_x * tw)
        fw = max(3, int(0.012 * tw))
        cv2.rectangle(img, (fx - fw // 2 - 1, y + 1), (fx + fw // 2 + 1, y + rh - 2), k["outline"], -1)
        cv2.rectangle(img, (fx - fw // 2 + 1, y + 2), (fx + fw // 2 - 1, y + rh - 3), k["fish"], -1)
        c = self.colors
        px, py, pw, ph = self._rect("progress")
        cv2.rectangle(img, (px, py), (px + pw, py + ph), k["frame"], -1)
        fill = int(pw * self.progress)
        if fill > 0:
            cv2.rectangle(img, (px, py), (px + fill, py + ph), hex_to_bgr(c.progress_color), -1)

    def _render_reel(self, img: np.ndarray) -> None:
        if self.skin:
            self._render_skinned_reel(img)
            return
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


def random_skin(seed: int) -> dict:
    """A random rod skin for the reel: colours, see-through bar and ornament frame (BGR tuples)."""
    r = random.Random(seed)

    def col(lo=0, hi=255):
        return tuple(r.randint(lo, hi) for _ in range(3))
    track_top = col(20, 140)
    return {
        "frame": col(10, 90), "ornament_col": col(60, 255), "ornament": r.choice([0.0, 0.08, 0.13]),
        "track_top": track_top, "track_bot": tuple(min(255, max(0, v + r.randint(-60, 60))) for v in track_top),
        "outline": col(0, 40), "bar": col(150, 255), "bar_alpha": r.uniform(0.35, 0.8), "fish": col(0, 255),
        "lit": tuple(min(255, v + 120) for v in track_top), "pointer": r.choice([(255, 255, 255), col(0, 60),
                                                                                    col(160, 255)]),
    }
