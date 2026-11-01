"""Real rod pictures, from the Fisch wiki (fischipedia.org).

They are not shipped with the app: on the player's PC a background thread asks the wiki's API which picture
belongs to each rod (50 rods per request), downloads the small thumbnails once and keeps them in the data
folder (``rod_images``). Until a picture is there, or for a rod the wiki has no picture of, the drawn rod
art is shown. Nothing is sent except the rod names in the API request. Can be switched off in Settings.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

API = "https://fischipedia.org/w/api.php"
ALLOWED_HOSTS = ("static.wikitide.net", "fischipedia.org")  # where the wiki keeps its images
USER_AGENT = "FischMacro (desktop app; rod pictures)"
THUMB = 160
REFRESH_DAYS = 14  # look up rods without a picture again after this long (the wiki grows)


def _fetch(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https hosts only
        return r.read(2_000_000)


def file_name(rod: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", rod).strip("_").lower() + ".png"


def parse_api(data: dict) -> dict[str, str | None]:
    """Rod title -> thumbnail URL (None when the page has no picture or does not exist)."""
    q = data.get("query", {}) if isinstance(data, dict) else {}
    alias: dict[str, str] = {}
    for key in ("normalized", "redirects"):
        for n in q.get(key, []) or []:
            alias[n.get("to", "")] = n.get("from", "")
    out: dict[str, str | None] = {}
    for page in (q.get("pages") or {}).values():
        title = page.get("title", "")
        url = (page.get("thumbnail") or {}).get("source")
        if url and urllib.parse.urlparse(url).hostname not in ALLOWED_HOSTS:
            url = None
        names = {title}
        # follow normalisation / redirects back to the name that was asked for
        frm = alias.get(title)
        while frm and frm not in names:
            names.add(frm)
            frm = alias.get(frm)
        for n in names:
            out[n] = url
    return out


class RodImages:
    def __init__(self, folder: Path, fetch: Callable[[str], bytes] = _fetch):
        self.folder = Path(folder)
        self.fetch = fetch
        self.index_path = self.folder / "index.json"
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.index: dict[str, dict] = {}
        try:
            self.index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.index = {}

    # ------------------------------------------------------------------ read
    def path(self, rod: str) -> Path | None:
        p = self.folder / file_name(rod)
        return p if p.is_file() and p.stat().st_size > 0 else None

    def url(self, rod: str) -> str | None:
        """file:// URL of the cached picture, for the interface (None = draw the rod art)."""
        p = self.path(rod)
        return p.resolve().as_uri() if p else None

    # ------------------------------------------------------------------ download
    def start(self, rods: list[str]) -> None:
        """Fill the cache in the background (no-op while a run is going)."""
        if self.thread is not None and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.update, args=(list(rods),), name="rod-pictures", daemon=True)
        self.thread.start()

    def _due(self, rod: str, now: float) -> bool:
        if self.path(rod):
            return False
        e = self.index.get(rod)
        return e is None or (e.get("url") is None and now - e.get("checked", 0) > REFRESH_DAYS * 86400) or \
            bool(e.get("url"))  # known URL but no file yet: download it

    def update(self, rods: list[str]) -> int:
        """Look up and download what is missing. Returns how many pictures were added."""
        now = time.time()
        todo = [r for r in rods if self._due(r, now)]
        if not todo:
            return 0
        self.folder.mkdir(parents=True, exist_ok=True)
        unknown = [r for r in todo if not (self.index.get(r) or {}).get("url")]
        for i in range(0, len(unknown), 50):
            batch = unknown[i:i + 50]
            q = urllib.parse.urlencode({"action": "query", "titles": "|".join(batch), "prop": "pageimages",
                                        "pithumbsize": THUMB, "format": "json", "redirects": 1})
            try:
                found = parse_api(json.loads(self.fetch(f"{API}?{q}")))
            except Exception as exc:  # noqa: BLE001 - offline or the wiki changed: keep the drawn art
                log.info("Rod pictures: wiki not reachable (%s)", exc)
                return 0
            with self.lock:
                for r in batch:
                    self.index[r] = {"url": found.get(r), "checked": now}
            time.sleep(0.2)
        added = 0
        for r in todo:
            url = (self.index.get(r) or {}).get("url")
            if not url:
                continue
            try:
                data = self.fetch(url)
            except Exception as exc:  # noqa: BLE001
                log.debug("Rod picture for %s not downloaded: %s", r, exc)
                continue
            if data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" or data[:4] == b"RIFF":
                (self.folder / file_name(r)).write_bytes(data)
                added += 1
            time.sleep(0.05)
        with self.lock:
            try:
                self.index_path.write_text(json.dumps(self.index), encoding="utf-8")
            except OSError:
                pass
        if added:
            log.info("Rod pictures: %d downloaded from the Fisch wiki", added)
        return added
