"""Rod pictures from the Fisch wiki: API answer parsing, download, cache, and staying offline-safe.
The API answer below is the wiki's real response (fetched 2026-11-01); no network is used here."""
import json

import cv2
import numpy as np

from fischmacro.ui.rod_images import RodImages, file_name, parse_api

REAL = {"batchcomplete": "", "query": {
    "normalized": [{"from": "Stellarwave_Melody", "to": "Stellarwave Melody"}],
    "pages": {
        "26015": {"pageid": 26015, "ns": 0, "title": "Abaia's Spite", "thumbnail": {
            "source": "https://static.wikitide.net/fischwiki/thumb/e/e6/Abaia%27s_Spite.png/160px-Abaia%27s_Spite.png"}},
        "20383": {"pageid": 20383, "ns": 0, "title": "Lullaby", "thumbnail": {
            "source": "https://static.wikitide.net/fischwiki/thumb/9/9a/Lullaby.png/160px-Lullaby.png"}},
        "25503": {"pageid": 25503, "ns": 0, "title": "Stellarwave Melody", "thumbnail": {
            "source": "https://static.wikitide.net/fischwiki/thumb/4/45/Stellarwave_Melody.png/160px-Stellarwave_Melody.png"}},
        "-1": {"ns": 0, "title": "No Such Rod", "missing": ""},
        "77": {"pageid": 77, "ns": 0, "title": "Evil Rod", "thumbnail": {"source": "https://evil.example/x.png"}},
    }}}
PNG = cv2.imencode(".png", np.full((40, 16, 3), 200, np.uint8))[1].tobytes()


def test_api_answer_is_read_and_foreign_hosts_ignored():
    m = parse_api(REAL)
    assert m["Lullaby"].endswith("160px-Lullaby.png")
    assert m["Stellarwave_Melody"] == m["Stellarwave Melody"]  # the name asked for maps back
    assert m["No Such Rod"] is None and m["Evil Rod"] is None


def test_download_once_then_from_cache(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        if "api.php" in url:
            return json.dumps(REAL).encode()
        return PNG

    imgs = RodImages(tmp_path, fetch)
    assert imgs.update(["Lullaby", "Abaia's Spite", "No Such Rod"]) == 2
    assert imgs.url("Lullaby").startswith("file://") and imgs.url("No Such Rod") is None
    assert (tmp_path / file_name("Lullaby")).read_bytes() == PNG
    n = len(calls)
    again = RodImages(tmp_path, fetch)  # a new run: index and files are reused, nothing fetched
    assert again.update(["Lullaby", "Abaia's Spite", "No Such Rod"]) == 0 and len(calls) == n


def test_offline_keeps_the_drawn_art(tmp_path):
    def fetch(url):
        raise OSError("no internet")

    imgs = RodImages(tmp_path, fetch)
    assert imgs.update(["Lullaby"]) == 0 and imgs.url("Lullaby") is None


def test_only_real_images_are_kept(tmp_path):
    def fetch(url):
        return json.dumps(REAL).encode() if "api.php" in url else b"<html>blocked</html>"

    imgs = RodImages(tmp_path, fetch)
    assert imgs.update(["Lullaby"]) == 0 and imgs.url("Lullaby") is None
