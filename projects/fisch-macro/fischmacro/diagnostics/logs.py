"""Logging: human-readable + JSON-lines files, plus an in-memory buffer for the UI."""
from __future__ import annotations

import json
import logging
import logging.handlers
import threading
import time
from collections import deque

from fischmacro import paths

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": round(record.created, 3), "level": record.levelname, "logger": record.name,
                   "msg": record.getMessage(), "thread": record.threadName}
        for key in ("kind", "state", "session"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class MemoryHandler(logging.Handler):
    """Keeps the most recent records for the UI's activity views."""

    def __init__(self, capacity: int = 2000):
        super().__init__()
        self.records: deque[tuple[float, str, str, str]] = deque(maxlen=capacity)
        self._lock2 = threading.Lock()
        self.counter = 0

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock2:
            self.records.append((record.created, record.levelname, record.name, record.getMessage()))
            self.counter += 1

    def since(self, counter: int) -> tuple[int, list[tuple[float, str, str, str]]]:
        with self._lock2:
            n = self.counter - counter
            items = list(self.records)[-n:] if n > 0 else []
            return self.counter, items


MEMORY = MemoryHandler()
_configured = False


def setup_logging(level: str = "INFO", max_files: int = 5, to_files: bool = True) -> None:
    global _configured
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if _configured:
        return
    _configured = True
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FMT))
    root.addHandler(console)
    root.addHandler(MEMORY)
    if to_files:
        d = paths.logs_dir()
        text = logging.handlers.RotatingFileHandler(d / "fischmacro.log", maxBytes=2_000_000,
                                                    backupCount=max_files, encoding="utf-8")
        text.setFormatter(logging.Formatter(_FMT))
        root.addHandler(text)
        js = logging.handlers.RotatingFileHandler(d / "fischmacro.jsonl", maxBytes=2_000_000,
                                                  backupCount=max_files, encoding="utf-8")
        js.setFormatter(JsonFormatter())
        root.addHandler(js)
    logging.Formatter.converter = time.localtime


def set_level(level: str) -> None:
    logging.getLogger().setLevel(getattr(logging, level.upper(), logging.INFO))
