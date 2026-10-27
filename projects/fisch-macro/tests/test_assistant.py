"""AI assistant: request shape and how its answers feed the macro (no network: the API call is faked)."""
import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from fischmacro.ai.assistant import Assistant, AssistantError, image_block
from fischmacro.profiles.schema import AiConfig


def msg(*blocks, stop="end_turn"):
    return NS(content=list(blocks), stop_reason=stop, model="claude-opus-5-5")


def test_not_configured_means_nothing_is_sent(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a = Assistant(lambda: AiConfig())
    with pytest.raises(AssistantError):
        a.ask("hi")


def test_ask_returns_text_and_sources(monkeypatch):
    cfg = AiConfig(api_key="k")
    a = Assistant(lambda: cfg)
    seen = {}

    def fake_call(**kw):
        seen.update(kw)
        return msg(NS(type="web_search_tool_result", content=[NS(url="https://fischipedia.org/wiki/Lullaby",
                                                                  title="Lullaby")]),
                   NS(type="text", text="Use Fortuitous Harmony for luck."))
    monkeypatch.setattr(a, "_call", fake_call)
    ans = a.ask("best lullaby mode?", np.zeros((40, 60, 3), np.uint8))
    assert "Fortuitous" in ans.text and ans.sources[0][1].startswith("https://fischipedia")
    assert any(t["type"] == "web_search_20260209" for t in seen["tools"])
    assert seen["messages"][-1]["content"][0]["type"] == "image"
    assert len(a.history) == 2   # conversation continues; screenshot is not kept in history


def test_read_screen_needs_permission_and_parses(monkeypatch):
    cfg = AiConfig(api_key="k")
    a = Assistant(lambda: cfg)
    with pytest.raises(AssistantError):
        a.read_screen(np.zeros((10, 10, 3), np.uint8))
    cfg.allow_screenshots = True
    reading = {"weather": "Rain", "time_of_day": "Night", "surge": "", "events": [], "hunts": ["Megalodon"],
               "rod": "Plaguereaver", "rod_skin": "", "enchant": "Abyssal", "minigame": "reel", "notes": ""}
    monkeypatch.setattr(a, "_call", lambda **kw: msg(NS(type="text", text=json.dumps(reading))))
    assert a.read_screen(np.zeros((10, 10, 3), np.uint8))["rod"] == "Plaguereaver"


def test_image_block_is_scaled_jpeg():
    b = image_block(np.zeros((3000, 4000, 3), np.uint8))
    assert b["source"]["media_type"] == "image/jpeg" and len(b["source"]["data"]) > 100
