"""Watchers (OCR), Discord notifications and automatic rod/skin profiles."""
import http.server
import json
import threading

import cv2
import numpy as np
import pytest

from fischmacro.automation.watchers import PRESET_WATCHERS, WatcherService
from fischmacro.diagnostics.notify import DiscordNotifier
from fischmacro.profiles.schema import NotificationsConfig, Region, Watcher
from fischmacro.vision.ocr import OcrEngine, find_keywords

ocr = pytest.mark.skipif(not OcrEngine.shared().available, reason="OCR engine not installed")


def screen_with(text, where=(0.3, 0.06), size=(720, 1280)):
    img = np.full((size[0], size[1], 3), (120, 80, 40), np.uint8)
    cv2.putText(img, text, (int(where[0] * size[1]), int(where[1] * size[0])), cv2.FONT_HERSHEY_DUPLEX, 1.0,
                (255, 255, 255), 2, cv2.LINE_AA)
    return img


def test_keyword_matching_is_case_and_punctuation_insensitive():
    assert find_keywords("THE MEGALODON HUNT HAS BEGUN!!", ["Megalodon", "Kraken"]) == ["Megalodon"]
    assert find_keywords("Great-White Shark", ["great white"]) == ["great white"]


@ocr
def test_hunt_watcher_alerts_once_per_cooldown():
    hits = []
    w = Watcher("Hunts", enabled=True, kind="hunt", region=Region(0.2, 0.0, 0.6, 0.12),
                keywords="Megalodon|Great White", cooldown_min=5)
    svc = WatcherService(lambda: [w], lambda: None, lambda w_, m, t, img: hits.append(m))
    img = screen_with("Megalodon Hunt has started!")
    assert svc.check(w, img, 0.0) == ["Megalodon"]
    assert svc.check(w, img, 10.0) == []            # same hunt, inside cooldown
    assert svc.check(w, img, 400.0) == ["Megalodon"]
    assert svc.check(w, screen_with("Clear skies"), 800.0) == []
    assert len(hits) == 2


@ocr
def test_rod_watcher_reports_name_changes():
    rods = []
    w = Watcher("Rod name", enabled=True, kind="rod", region=Region(0.25, 0.85, 0.5, 0.1))
    svc = WatcherService(lambda: [w], lambda: None, lambda *a: None, rods.append)
    svc.check(w, screen_with("Stellarwave Melody Rod", where=(0.3, 0.91)), 0.0)
    svc.check(w, screen_with("Stellarwave Melody Rod", where=(0.3, 0.91)), 10.0)
    svc.check(w, screen_with("Rod of the Depths", where=(0.3, 0.91)), 20.0)
    from fischmacro.vision.ocr import fuzzy_contains
    assert len(rods) == 2 and fuzzy_contains(rods[0], "stellarwave") and fuzzy_contains(rods[1], "depths")


def test_watcher_presets_are_off_by_default():
    assert {w.name for w in PRESET_WATCHERS} >= {"Hunts", "Weather", "Server events", "Rod charge", "Rod name"}
    assert all(not w.enabled for w in PRESET_WATCHERS)


class _Hook(http.server.BaseHTTPRequestHandler):
    received = []

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Hook.received.append((self.headers["Content-Type"], body))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_discord_webhook_payload_and_rate_limit():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = NotificationsConfig(discord_webhook=f"http://127.0.0.1:{srv.server_port}/hook", discord_mention="<@1>")
    n = DiscordNotifier(lambda: cfg)
    assert n.send("Megalodon detected", "Hunt started", key="m")
    assert not n.send("Megalodon detected", "Hunt started", key="m")  # rate-limited
    n._thread.join(timeout=5)
    srv.shutdown()
    ctype, body = _Hook.received[0]
    payload = json.loads(body)
    assert ctype == "application/json" and payload["content"] == "<@1>"
    assert payload["embeds"][0]["title"] == "Megalodon detected"


def test_discord_does_nothing_without_webhook():
    n = DiscordNotifier(lambda: NotificationsConfig())
    assert not n.configured and not n.send("x", "y")


def test_screenshot_only_attached_when_allowed():
    cfg = NotificationsConfig(discord_webhook="http://127.0.0.1:9/none")
    n = DiscordNotifier(lambda: cfg)
    n._q.put = lambda item, *a, **k: None
    sent = []
    n._q.put_nowait = sent.append
    n._thread = threading.Thread()  # pretend a worker exists
    n._thread.is_alive = lambda: True
    n.send("a", "b", image=np.zeros((4, 4, 3), np.uint8), key="1")
    assert sent[-1][2] is None                       # discord_screenshot is off by default
    cfg.discord_screenshot = True
    n.send("a", "b", image=np.zeros((4, 4, 3), np.uint8), key="2")
    assert sent[-1][2] is not None


@pytest.fixture
def ctx(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from fischmacro.app.context import AppContext
    from fischmacro.diagnostics.stats import StatsStore
    from fischmacro.profiles.manager import ProfileManager, SettingsStore
    c = AppContext(SettingsStore(tmp_path / "s.json"), ProfileManager(tmp_path / "p"), StatsStore(tmp_path / "db"))
    yield c
    c.engine.shutdown()


def test_new_rod_creates_profile_with_preset(ctx):
    ctx.handle_rod("Stellarwave Melody Rod")
    assert ctx.profile.name.startswith("Stellarwave Melody Rod")
    assert ctx.profile.minigame.kind == "stellarwave"
    assert ctx.profiles.exists(ctx.profile.name)
    first = ctx.profile.name
    ctx.handle_rod("Rod of the Depths")
    assert ctx.profile.name.startswith("Rod of the Depths") and ctx.profile.minigame.kind == "stellarwave"
    ctx.handle_rod("Stellarwave Melody Rod")        # known rod again: switch back, no new profile
    assert ctx.profile.name == first
    assert len(ctx.profiles.names()) == 3


def test_new_skin_on_calibrated_rod_becomes_its_own_profile(ctx):
    ctx.handle_rod("Lullaby")
    p = ctx.profile
    p.detection.bar_color, p.detection.fish_color = "#AAAAAA", "#111111"
    ctx.save_profile()
    original = p.name
    # auto-adapt found a different skin
    p.detection.bar_color, p.detection.fish_color = "#55CCFF", "#330000"
    ctx._on_auto_changed("adapt", {"old_bar": "#AAAAAA", "old_fish": "#111111", "new_bar": "#55CCFF",
                                   "new_fish": "#330000"})
    assert ctx.profile.name != original and "skin" in ctx.profile.name
    assert ctx.profiles.load(original).detection.bar_color == "#AAAAAA"   # old skin kept
    assert ctx.profiles.load(ctx.profile.name).detection.bar_color == "#55CCFF"


def test_fuzzy_matching_tolerates_ocr_errors_but_not_short_words():
    from fischmacro.vision.ocr import fuzzy_contains
    assert fuzzy_contains("Stellrwave Melody Rod", "Stellarwave")
    assert fuzzy_contains("Megal0don Hunt", "Megalodon")
    assert not fuzzy_contains("Hint of rain", "Hunt")
    assert not fuzzy_contains("Rod of the Depths", "Stellarwave")
