"""Optional Discord (webhook) notifications. Nothing is sent unless a webhook URL is set."""
from __future__ import annotations

import io
import json
import logging
import queue
import threading
import time
import urllib.request
import uuid

import cv2

from fischmacro import APP_NAME

log = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, get_config):
        self.get_config = get_config  # -> NotificationsConfig
        self._q: queue.Queue = queue.Queue(maxsize=50)
        self._thread: threading.Thread | None = None
        self._last: dict[str, float] = {}
        self.sent = 0
        self.last_error = ""

    @property
    def configured(self) -> bool:
        url = (self.get_config().discord_webhook or "").strip()
        return url.startswith("https://") or url.startswith("http://127.0.0.1") or url.startswith("http://localhost")

    def send(self, title: str, message: str, image=None, key: str | None = None, min_gap: float = 10.0,
             error: bool = False) -> bool:
        """Queue a message. ``key`` rate-limits repeats of the same alert."""
        if not self.configured:
            return False
        now = time.monotonic()
        k = key or title
        if now - self._last.get(k, -1e9) < min_gap:
            return False
        self._last[k] = now
        cfg = self.get_config()
        if image is not None and not cfg.discord_screenshot:
            image = None
        try:
            self._q.put_nowait((title, message, image, error))
        except queue.Full:
            return False
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker, name="discord", daemon=True)
            self._thread.start()
        return True

    def _worker(self) -> None:
        while True:
            try:
                title, message, image, error = self._q.get(timeout=30)
            except queue.Empty:
                return
            try:
                self._post(title, message, image, error)
                self.sent += 1
                self.last_error = ""
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                log.warning("Discord notification failed: %s", exc)

    def _post(self, title: str, message: str, image, error: bool) -> None:
        cfg = self.get_config()
        content = f"{cfg.discord_mention} " if cfg.discord_mention else ""
        payload = {"username": APP_NAME, "content": content.strip() or None,
                   "embeds": [{"title": title[:250], "description": message[:3900],
                               "color": 0xEF4444 if error else 0x8B5CF6,
                               "footer": {"text": time.strftime("%Y-%m-%d %H:%M:%S")}}]}
        url = cfg.discord_webhook.strip()
        if image is not None:
            ok, png = cv2.imencode(".png", image)
            boundary = uuid.uuid4().hex
            body = io.BytesIO()
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                       f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n".encode())
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"screen.png\"\r\n"
                       f"Content-Type: image/png\r\n\r\n".encode())
            body.write(png.tobytes())
            body.write(f"\r\n--{boundary}--\r\n".encode())
            data, ctype = body.getvalue(), f"multipart/form-data; boundary={boundary}"
        else:
            data, ctype = json.dumps(payload).encode(), "application/json"
        req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype, "User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - user-provided webhook
            resp.read()
