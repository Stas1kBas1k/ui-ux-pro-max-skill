"""Local text recognition (RapidOCR / ONNX Runtime). Runs entirely on this PC.

Used for hunt/weather/event watchers, reading the equipped rod's name and
finding buttons by their text in routines. The model loads lazily on first
use (~1-2 s) and is shared between threads.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class TextBox:
    text: str
    confidence: float
    x: float      # centre, normalised to the image the OCR ran on
    y: float
    w: float
    h: float


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", text.lower())).strip()


class OcrEngine:
    _instance: OcrEngine | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()
        self.error = ""

    @classmethod
    def shared(cls) -> OcrEngine:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def available(self) -> bool:
        if self._engine is None and not self.error:
            self._load()
        return self._engine is not None

    def _load(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            self._engine = RapidOCR()
        except Exception as exc:  # noqa: BLE001
            self.error = f"OCR unavailable: {exc}"
            log.warning(self.error)

    def read(self, image: np.ndarray | None, min_conf: float = 0.5) -> list[TextBox]:
        if image is None or image.size == 0 or not self.available:
            return []
        h, w = image.shape[:2]
        scale = 1.0
        if h < 48:  # small crops read much better upscaled
            scale = 48.0 / h
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        with self._lock:
            try:
                result, _ = self._engine(image)
            except Exception as exc:  # noqa: BLE001
                log.warning("OCR failed: %s", exc)
                return []
        out = []
        for box, text, conf in result or []:
            conf = float(conf)
            if conf < min_conf:
                continue
            pts = np.array(box, dtype=np.float32) / scale
            x0, y0 = pts.min(axis=0)
            x1, y1 = pts.max(axis=0)
            out.append(TextBox(str(text), conf, (x0 + x1) / 2 / w, (y0 + y1) / 2 / h, (x1 - x0) / w, (y1 - y0) / h))
        return out

    def text(self, image: np.ndarray | None) -> str:
        return " ".join(b.text for b in self.read(image))


def _word_ok(word: str, words: list[str]) -> bool:
    from difflib import SequenceMatcher
    if word in words:
        return True
    if len(word) < 5:  # short words must match exactly (avoid false alarms)
        return False
    return any(len(w) >= 4 and SequenceMatcher(None, word, w).ratio() >= 0.8 for w in words)


def fuzzy_contains(text: str, phrase: str) -> bool:
    """True if every word of ``phrase`` appears in ``text``, allowing small OCR errors."""
    t, p = normalize(text), normalize(phrase)
    if not p:
        return False
    if p in t:
        return True
    words = t.split()
    return all(_word_ok(w, words) for w in p.split())


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    """Keywords that occur in text (case/punctuation-insensitive, tolerant to small OCR errors)."""
    return [k for k in keywords if fuzzy_contains(text, k)]


def find_text_box(boxes: list[TextBox], wanted: str) -> TextBox | None:
    w = normalize(wanted)
    hits = [b for b in boxes if w and w in normalize(b.text)]
    return max(hits, key=lambda b: b.confidence) if hits else None
