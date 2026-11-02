"""Bar and fish on decorated reel skins, from the player's recordings (reel area only, labelled by hand).

Before: the colour finder took the white fang teeth inside Halibut Crimson Excision's red bar for the bar, the
Remembrance reel area lay below the track (that skin draws it higher), and Remembrance's dark decoy line was
followed instead of the white fish. The labelled frames of all recorded skins: bar right 10/29, fish 16/29;
now 24/29 and 25/29 (these three skins are the regression set kept in the repository).
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from fischmacro.profiles.schema import Profile
from fischmacro.vision.engine import VisionEngine
from fischmacro.vision.frame import Frame

HERE = Path(__file__).parent / "fixtures" / "reels"
LABELS = json.loads((HERE / "labels.json").read_text())


def _replay(name: str, profile: Profile):
    cap = cv2.VideoCapture(str(HERE / f"{name}.mp4"))
    x0, y0 = LABELS[name]["band"]
    v = VisionEngine(profile)
    v.verify_shake = False
    out, i = {}, 0
    while True:
        ok, band = cap.read()
        if not ok:
            break
        img = np.zeros((1080, 1920, 3), np.uint8)
        img[y0:y0 + band.shape[0], x0:x0 + band.shape[1]] = band
        o = v.process(Frame(img, (1920, 1080), timestamp=i / 40), v.regions_for("REELING"), "REELING")
        if str(i) in LABELS[name]["frames"]:
            out[i] = o.reel
        i += 1
    if i < 20:
        pytest.skip("reel clip not readable")
    return out


def _score(name: str, profile: Profile) -> tuple[int, int, int]:
    got = _replay(name, profile)
    bars = fish = 0
    for i, r in got.items():
        bl, br, fx = LABELS[name]["frames"][str(i)]
        if r.bar_found and abs(r.bar_center - (bl + br) / 2) < 0.03 and abs((r.bar_right - r.bar_left) - (br - bl)) < 0.06:
            bars += 1
        if r.fish_found and abs(r.fish_x - fx) < 0.02:
            fish += 1
    return bars, fish, len(got)


def test_halibut_crimson_bar_is_the_red_block_not_the_fang():
    bars, fish, n = _score("halibut_crimson", Profile())
    assert n == 3 and bars == 3


def test_remembrance_track_is_found_higher_up_and_the_white_fish_followed():
    p = Profile()
    p.detection.fish_line = "bright"  # the Remembrance preset
    bars, fish, n = _score("remembrance_living", p)
    assert n == 3 and bars >= 2 and fish >= 2


def test_basic_skin_still_reads_right():
    bars, fish, n = _score("basic", Profile())
    assert n == 4 and bars == 4 and fish == 4
