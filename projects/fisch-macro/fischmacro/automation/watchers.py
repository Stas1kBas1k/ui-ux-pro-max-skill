"""Text watchers: read screen regions with OCR and react to hunts, weather, events and the rod name.

Runs on its own low-priority thread using the latest full frame, so the
fishing loop never waits for OCR.
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from fischmacro.profiles.schema import Region, Watcher
from fischmacro.vision.ocr import OcrEngine, find_keywords, fuzzy_contains

log = logging.getLogger(__name__)


@dataclass
class WatchState:
    text: str = ""
    matches: list[str] = field(default_factory=list)
    last_check: float = -1e9
    last_alert: dict[str, float] = field(default_factory=dict)


def _keywords(value: str) -> list[str]:
    return [k.strip() for k in value.split("|") if k.strip()]


def crop_region(image, region: Region):
    h, w = image.shape[:2]
    x, y, rw, rh = region.to_rect(w, h)
    return image[y:y + rh, x:x + rw]


class WatcherService:
    def __init__(self, get_watchers: Callable[[], list[Watcher]], get_image: Callable[[], object],
                 on_match: Callable[[Watcher, list[str], str, object], None],
                 on_rod: Callable[[str], None] | None = None, ocr: OcrEngine | None = None):
        self.get_watchers = get_watchers
        self.get_image = get_image
        self.on_match = on_match
        self.on_rod = on_rod
        self.ocr = ocr
        self.states: dict[str, WatchState] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_rod = ""

    # -- pure logic (testable)
    def check(self, w: Watcher, image, now: float) -> list[str]:
        """Run one watcher on one image; returns newly alerted matches."""
        st = self.states.setdefault(w.name, WatchState())
        st.last_check = now
        crop = crop_region(image, w.region)
        ocr = self.ocr or OcrEngine.shared()
        text = ocr.text(crop)
        st.text = text
        if w.kind == "rod":
            name = self._rod_name(text)
            if name and not (self.last_rod and fuzzy_contains(name, self.last_rod) and fuzzy_contains(self.last_rod, name)):
                self.last_rod = name
                if self.on_rod:
                    self.on_rod(name)
            st.matches = [name] if name else []
            return []
        words = _keywords(w.keywords)
        matches = find_keywords(text, words) if words else ([text] if text else [])
        st.matches = matches
        fresh = [m for m in matches if now - st.last_alert.get(m, -1e9) >= w.cooldown_min * 60]
        for m in fresh:
            st.last_alert[m] = now
        if fresh:
            self.on_match(w, fresh, text, image)
        return fresh

    @staticmethod
    def _rod_name(text: str) -> str:
        text = " ".join(text.split())
        if len(text) < 3 or sum(ch.isalpha() for ch in text) < 3:
            return ""
        return text[:60]

    # -- thread
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="watchers", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(0.5):
            watchers = [w for w in self.get_watchers() if w.enabled]
            if not watchers:
                continue
            now = time.monotonic()
            due = [w for w in watchers if now - self.states.get(w.name, WatchState()).last_check >= w.interval_s]
            if not due:
                continue
            image = self.get_image()
            if image is None:
                continue
            for w in due:
                try:
                    self.check(w, image, now)
                except Exception:  # noqa: BLE001
                    log.exception("Watcher %s failed", w.name)


PRESET_WATCHERS: list[Watcher] = [
    Watcher("Hunts", kind="hunt", region=Region(0.2, 0.0, 0.6, 0.16),
            keywords="Megalodon|Great White|Great Hammerhead|Whale Shark|Shark Hunt|Orca|Kraken|Hunt",
            note="Server announcement text at the top of the screen. Remove hunts you don't care about."),
    Watcher("Weather", kind="weather", region=Region(0.0, 0.0, 0.3, 0.1),
            keywords="Rain|Foggy|Windy|Clear|Aurora|Eclipse|Snow|Storm", cooldown_min=15,
            note="Point the region at the in-game weather / season display."),
    Watcher("Server events", kind="event", region=Region(0.2, 0.0, 0.6, 0.16),
            keywords="Lucky Pool|Fish Abundance|Nuke|Avalanche|Skies of Anguish|Snowstorm|Lunar Eclipse|"
                     "Abyssal Alignment|Meteor",
            note="Admin and astral events. Pair with routines to pop potions or totems when one starts."),
    Watcher("Rod charge", kind="custom", region=Region(0.3, 0.8, 0.4, 0.1), keywords="Recharge|Out of charge|No charge",
            cooldown_min=2, notify_discord=False,
            note="Triggers the 'Sovereign recharge' routine. Point it where the rod charge message appears."),
    Watcher("Rod name", kind="rod", region=Region(0.3, 0.86, 0.4, 0.08), interval_s=8, notify_discord=False,
            toast=False, note="Reads the equipped rod's name (e.g. from the hotbar tooltip) to pick its profile."),
]


def preset_copies() -> list[Watcher]:
    return [copy.deepcopy(w) for w in PRESET_WATCHERS]
