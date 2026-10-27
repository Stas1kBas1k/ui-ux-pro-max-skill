"""The in-app AI assistant, powered by Claude.

Two jobs:
- ``ask``: answer any question (Fisch or not) with up-to-date info, using Claude's web search and web fetch
  tools, and optionally a screenshot of the game.
- ``read_screen``: look at one game screenshot and report weather, time of day, events, hunts, the rod,
  its skin and enchant as structured data, so the macro can react to what is on screen.

Nothing is sent anywhere until the user adds an API key. Screenshots are sent only when the user allows it.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field

import cv2
import numpy as np

log = logging.getLogger(__name__)

SYSTEM = (
    "You are the assistant inside Fisch Macro, a desktop helper for the Roblox fishing game Fisch. "
    "Answer the player's questions clearly and briefly, like a friend who knows the game well. "
    "For anything about Fisch (rods, enchants, baits, fish, locations, events, hunts, weather, totems, "
    "updates, codes), search the web first: the game updates often and your memory may be out of date. "
    "Prefer the official Fisch wiki (fischipedia.org) and recent sources, and say when information is "
    "uncertain or may have changed. Questions about anything else are welcome too. "
    "If a screenshot is attached, it shows the player's game right now. "
    "Use short paragraphs or bullet points; no long preambles."
)

SCREEN_SCHEMA = {
    "type": "object",
    "properties": {
        "weather": {"type": "string", "description": "Weather shown, e.g. Clear, Rain, Foggy, Windy, Aurora Borealis; empty if not visible"},
        "time_of_day": {"type": "string", "description": "Day or Night; empty if unknown"},
        "surge": {"type": "string", "description": "Active surge (Shiny, Sparkling, Mutation) or empty"},
        "events": {"type": "array", "items": {"type": "string"}, "description": "Server events or announcements visible"},
        "hunts": {"type": "array", "items": {"type": "string"}, "description": "Hunts announced, e.g. Megalodon"},
        "rod": {"type": "string", "description": "Name of the equipped fishing rod, if readable"},
        "rod_skin": {"type": "string", "description": "Rod skin name if visible"},
        "enchant": {"type": "string", "description": "Rod enchant if visible"},
        "minigame": {"type": "string", "description": "none, reel, shake, lullaby, stellarwave or other"},
        "notes": {"type": "string", "description": "Anything else useful for an AFK fisher, one sentence"},
    },
    "required": ["weather", "time_of_day", "surge", "events", "hunts", "rod", "rod_skin", "enchant",
                 "minigame", "notes"],
    "additionalProperties": False,
}

WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3},
]


class AssistantError(Exception):
    pass


@dataclass
class Answer:
    text: str
    sources: list[tuple[str, str]] = field(default_factory=list)   # (title, url)
    model: str = ""


def image_block(img_bgr: np.ndarray, max_side: int = 1568) -> dict:
    """A JPEG image content block, scaled so the long side is at most ``max_side``."""
    h, w = img_bgr.shape[:2]
    s = min(1.0, max_side / max(h, w))
    if s < 1.0:
        img_bgr = cv2.resize(img_bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise AssistantError("Could not encode the screenshot")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(buf.tobytes()).decode("ascii")}}


class Assistant:
    def __init__(self, get_config):
        self.get_config = get_config
        self.history: list[dict] = []
        self._client = None
        self._key = None

    @property
    def configured(self) -> bool:
        return bool(self.get_config().api_key.strip() or os.environ.get("ANTHROPIC_API_KEY"))

    def _client_for_key(self):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - packaged builds include it
            raise AssistantError("The 'anthropic' package is not installed") from exc
        key = self.get_config().api_key.strip() or None
        if self._client is None or key != self._key:
            self._client = anthropic.Anthropic(api_key=key, max_retries=2)
            self._key = key
        return self._client

    def _call(self, **kwargs):
        """One request with refusal fallback; resumes server-tool turns that pause."""
        import anthropic
        cfg = self.get_config()
        client = self._client_for_key()
        messages = kwargs.pop("messages")
        try:
            for _ in range(4):
                with client.beta.messages.stream(
                    model=cfg.model, max_tokens=16000, messages=messages,
                    output_config={"effort": cfg.effort, **kwargs.pop("output_extra", {})},
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs,
                ) as stream:
                    msg = stream.get_final_message()
                if msg.stop_reason == "pause_turn":
                    messages = messages + [{"role": "assistant", "content": msg.content}]
                    continue
                return msg
        except anthropic.AuthenticationError as exc:
            raise AssistantError("The API key was not accepted - check it in Settings > AI assistant") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AssistantError("This API key cannot use this model") from exc
        except anthropic.RateLimitError as exc:
            raise AssistantError("Too many requests right now - try again in a minute") from exc
        except anthropic.APIConnectionError as exc:
            raise AssistantError("No connection to the AI service - check your internet") from exc
        except anthropic.APIStatusError as exc:
            raise AssistantError(f"The AI service returned an error ({exc.status_code})") from exc
        raise AssistantError("The answer took too many steps - try a more specific question")

    def ask(self, question: str, screenshot: np.ndarray | None = None) -> Answer:
        if not self.configured:
            raise AssistantError("Add your Claude API key in Settings > AI assistant first")
        content: list[dict] = []
        if screenshot is not None:
            content.append(image_block(screenshot))
        content.append({"type": "text", "text": question})
        turn = {"role": "user", "content": content}
        msg = self._call(system=SYSTEM, messages=self.history[-12:] + [turn], tools=WEB_TOOLS)
        if msg.stop_reason == "refusal":
            raise AssistantError("The assistant declined to answer that")
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        sources: list[tuple[str, str]] = []
        for b in msg.content:
            if b.type == "web_search_tool_result" and isinstance(b.content, list):
                for r in b.content:
                    url = getattr(r, "url", "")
                    if url and all(url != u for _, u in sources):
                        sources.append((getattr(r, "title", url), url))
        # keep the conversation going (text only: screenshots are not re-sent every turn)
        self.history += [{"role": "user", "content": question},
                         {"role": "assistant", "content": text or "(no answer)"}]
        return Answer(text or "(no answer)", sources[:6], getattr(msg, "model", ""))

    def reset(self) -> None:
        self.history.clear()

    def read_screen(self, screenshot: np.ndarray) -> dict:
        if not self.configured:
            raise AssistantError("Add your Claude API key in Settings > AI assistant first")
        if not self.get_config().allow_screenshots:
            raise AssistantError("Allow the assistant to see the game in Settings > AI assistant first")
        msg = self._call(
            system="You read Roblox Fisch screenshots for an AFK fishing helper. Report only what is visible.",
            messages=[{"role": "user", "content": [
                image_block(screenshot),
                {"type": "text", "text": "What does this Fisch screen show? Fill every field; use empty values "
                                         "for anything not visible."}]}],
            output_extra={"format": {"type": "json_schema", "schema": SCREEN_SCHEMA}},
        )
        if msg.stop_reason == "refusal":
            raise AssistantError("The assistant declined to read this screenshot")
        text = next((b.text for b in msg.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AssistantError("The screen reading came back incomplete") from exc
