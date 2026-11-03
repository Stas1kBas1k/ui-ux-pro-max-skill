"""Reading key prompts off the screen ("SHIFT" on the MiguRod counterattack bar, and the like).

OCR takes a few hundred milliseconds, far too slow for the per-frame loop, so prompts are read on a
background thread from the latest crop handed in; the per-frame code uses the last answer and falls back
to the configured key until one arrives. Only keys on an allow-list are ever pressed, so a stray letter
in chat or a name tag can never trigger an input.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass

# what a prompt can say -> the key name the input layer understands
KEY_WORDS = {"shift": "shift", "space": "space", "spacebar": "space", "ctrl": "ctrl", "control": "ctrl",
             "alt": "alt", "enter": "enter", "tab": "tab"}
SINGLE_KEYS = set("efrgzxcv")  # single letters: only when the text box holds nothing else


@dataclass
class KeyPrompt:
    key: str
    x: float
    y: float
    confidence: float
    text: str


def parse_key_prompts(boxes, allowed: set[str] | None = None) -> list[KeyPrompt]:
    """Key prompts among OCR text boxes, best first."""
    out = []
    for b in boxes:
        t = re.sub(r"[^a-z]", "", b.text.lower())
        key = KEY_WORDS.get(t)
        if key is None and len(t) == 1 and t in SINGLE_KEYS and len(b.text.strip()) <= 3:
            key = t
        if key is None:
            # a key cap read with one stray character ("SHIFTI", "lSHIFT"); never a word inside a sentence
            key = next((v for k, v in KEY_WORDS.items() if len(k) >= 4 and k in t and len(t) - len(k) <= 1), None)
        if key is not None and (allowed is None or key in allowed):
            out.append(KeyPrompt(key, b.x, b.y, b.confidence, b.text))
    return sorted(out, key=lambda p: -p.confidence)


class PromptReader:
    """Reads the key prompt of the latest crop on a background thread."""

    def __init__(self, ocr=None, allowed: set[str] | None = None):
        self._ocr = ocr
        self.allowed = allowed
        self._lock = threading.Lock()
        self._pending = None
        self._busy = False
        self.result: KeyPrompt | None = None
        self.result_at = 0.0
        self.read_ms = 0.0

    def reset(self) -> None:
        with self._lock:
            self._pending, self.result, self.result_at = None, None, 0.0

    def request(self, image) -> None:
        if image is None:
            return
        with self._lock:
            self._pending = image.copy()
            if self._busy:
                return
            self._busy = True
        threading.Thread(target=self._run, name="prompt-ocr", daemon=True).start()

    def _run(self) -> None:
        from fischmacro.vision.ocr import OcrEngine
        ocr = self._ocr or OcrEngine.shared()
        while True:
            with self._lock:
                img, self._pending = self._pending, None
                if img is None:
                    self._busy = False
                    return
            t0 = time.perf_counter()
            try:
                found = parse_key_prompts(ocr.read(img), self.allowed) if ocr.available else []
            except Exception:  # noqa: BLE001 - a failed read just means "no prompt seen"
                found = []
            with self._lock:
                self.read_ms = (time.perf_counter() - t0) * 1000
                if found:
                    self.result, self.result_at = found[0], time.perf_counter()
