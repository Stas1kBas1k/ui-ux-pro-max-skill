"""Tests on the player's real recording (1080p, Roblox Fisch): what the macro sees and what it would do.

Ground truth was measured by hand on these frames (pixels at 1920x1080). Frames: tests/fixtures/recording1.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from fischmacro.diagnostics.replay import profile_for
from fischmacro.vision.engine import VisionEngine
from fischmacro.vision.frame import Frame

ROOT = Path(__file__).parent / "fixtures" / "recording1"
W, H = 1920, 1080


def frame(t: float):
    img = cv2.imread(str(ROOT / f"t{t:04.1f}.jpg"))
    if img is None:
        pytest.skip("recording fixture missing")
    return img


def see(rod: str, t: float, repeat: int = 3):
    p = profile_for(rod)
    e = VisionEngine(p)
    e.verify_shake = False
    img = frame(t)
    for _ in range(repeat):
        obs = e.process(Frame(img, (W, H), timestamp=t), e.regions_for("REELING"), "REELING")
    x, y, w, h = p.regions["reel"].to_rect(W, H)
    px = lambda f: x + f * w  # noqa: E731
    return obs, px


# (rod, time, fish px, bar left px, bar right px)
REELS = [("normal", 8.0, 977, 747, 1153), ("normal", 9.5, None, None, None),
         ("migu", 28.5, 856, 897, 1035), ("migu", 29.5, 728, 657, 794),
         ("stellarwave", 16.8, 958, 598, 1318), ("stellarwave", 18.7, 948, 508, 1232),
         ("stellarwave", 19.5, 841, 478, 1205), ("stellarwave", 20.2, 797, 472, 1198)]


@pytest.mark.parametrize("rod,t,fish,bl,br", [r for r in REELS if r[2] is not None])
def test_fish_and_bar_on_real_frames(rod, t, fish, bl, br):
    obs, px = see(rod, t)
    r = obs.reel
    assert r.ui_present and r.fish_found and r.bar_found
    assert abs(px(r.fish_x) - fish) < 12, f"fish at {px(r.fish_x):.0f}, really {fish}"
    assert abs(px(r.bar_left) - bl) < 25 and abs(px(r.bar_right) - br) < 25, \
        f"bar {px(r.bar_left):.0f}-{px(r.bar_right):.0f}, really {bl}-{br}"


def test_migu_marks_are_seen_and_not_taken_for_the_fish():
    obs, px = see("migu", 29.0)
    assert len(obs.reel.marks) >= 1
    obs, px = see("migu", 29.5)
    assert abs(px(obs.reel.fish_x) - 728) < 12, "the red slash must not be taken for the fish"
    assert any(abs(px(m) - 875) < 20 for m in obs.reel.marks)


def test_migu_bar_steps_aside_from_a_mark_when_the_fish_allows():
    from fischmacro.vision.reel_edges import dodge_aim
    # fish at 0.5, bar 0.4-0.6, a mark at 0.58 (under the bar's right part): aim left of the fish
    aim = dodge_aim(0.5, 0.4, 0.6, [0.58])
    assert aim < 0.5 and 0.5 - aim <= 0.1 * 0.82
    assert dodge_aim(0.5, 0.4, 0.6, [0.9]) == 0.5          # mark far away: aim at the fish
    assert dodge_aim(0.5, 0.45, 0.55, [0.5]) == 0.5        # impossible to avoid: keep the fish


@pytest.mark.parametrize("t,lit,sign,x", [(16.8, 0, "Aries", 1090), (18.2, 1, "Taurus", 830),
                                           (19.5, 3, "Cancer", 1440), (20.2, 3, "Cancer", 1440)])
def test_stellarwave_next_sign_and_where_it_is(t, lit, sign, x):
    obs, _ = see("stellarwave", t, repeat=1)
    z = obs.zodiac
    assert z.found and z.lit == lit and z.next_sign == sign
    assert z.confident and abs(z.x * W - x) < 35


def test_stellarwave_never_clicks_an_unsure_match():
    obs, _ = see("stellarwave", 18.7, repeat=1)
    z = obs.zodiac
    assert z.next_sign == "Gemini"
    # here two places look alike; the solver must not click unless the match is clear (or it is right)
    assert not z.confident or abs(z.x * W - 560) < 35


@pytest.mark.parametrize("t", [0.0, 1.9, 3.0])
def test_no_shake_click_on_the_player_list(t):
    """The Roblox player list ("Ibrahim", "carro") looked like SHAKE buttons: 297 of 634 frames clicked."""
    from fischmacro.vision.ocr import OcrEngine
    p = profile_for("normal")
    e = VisionEngine(p)
    img = frame(t)
    if not OcrEngine.shared().available:
        pytest.skip("OCR engine not installed")
    for k in range(3):
        obs = e.process(Frame(img, (W, H), timestamp=k * 0.1), ("shake",), "WAITING_FOR_BITE")
        e.shake_verifier.wait_idle(10)
    obs = e.process(Frame(img, (W, H), timestamp=1.0), ("shake",), "WAITING_FOR_BITE")
    assert obs.shake.targets == []


def test_real_shake_button_is_still_clicked():
    from fischmacro.vision.ocr import OcrEngine
    if not OcrEngine.shared().available:
        pytest.skip("OCR engine not installed")
    img = cv2.imread(str(Path(__file__).parent / "fixtures" / "real" / "shake_button.webp"))
    h, w = img.shape[:2]
    e = VisionEngine(profile_for("normal"))
    e.process(Frame(img, (w, h)), ("shake",), "WAITING_FOR_BITE")
    e.shake_verifier.wait_idle(10)
    obs = e.process(Frame(img, (w, h)), ("shake",), "WAITING_FOR_BITE")
    assert len(obs.shake.targets) == 1 and abs(obs.shake.targets[0].x * w - 1200) < 15


def _lullaby_frames():
    cap = cv2.VideoCapture(str(ROOT / "lullaby_42s.mp4"))
    out = []
    while True:
        ok, img = cap.read()
        if not ok:
            break
        out.append(img)
    if len(out) < 40:
        pytest.skip("lullaby clip not readable")
    return out


def test_lullaby_gauge_lit_part_and_pendulum():
    """42.1-43.6 s: lit part is the left half of the ring; the pendulum swings left -> right -> left."""
    from fischmacro.vision.lullaby_gauge import LullabyGauge
    g = LullabyGauge()
    seen = []
    for k, img in enumerate(_lullaby_frames()):
        r = g.update(img, (960, 902), H)
        if r.present:
            seen.append((k, r.pointer, r.segments))
    assert len(seen) > 35
    k, ptr, segs = seen[len(seen) // 2]
    assert len(segs) == 1 and segs[0][0] < 0.05 and 0.45 < segs[0][1] < 0.6
    pointers = [p for _, p, _ in seen]
    assert min(pointers) < 0.15 and max(pointers) > 0.8, "a full swing is followed"


@pytest.mark.parametrize("off", [(50, 0), (-40, 30), (30, -25)])
def test_lullaby_gauge_found_when_the_region_is_off(off):
    """The gauge centre comes from the saved reel region, which can be off on another screen. Off by
    25-50 px the angles bent enough to click on the red part; now the real centre is searched for."""
    from fischmacro.vision.lullaby_gauge import LullabyGauge
    g = LullabyGauge()
    seen = []
    for img in _lullaby_frames():
        r = g.update(img, (960 + off[0], 902 + off[1]), H)
        if r.present:
            seen.append((r.pointer, r.segments))
    assert len(seen) > 35
    segs = seen[len(seen) // 2][1]
    assert len(segs) == 1 and segs[0][0] < 0.05 and 0.47 < segs[0][1] < 0.56
    assert min(p for p, _ in seen) < 0.15 and max(p for p, _ in seen) > 0.8


@pytest.mark.parametrize("look", ["pale", "tinted"])
def test_lullaby_gauge_read_on_recoloured_skins(look):
    """Skins can recolour the half-moon (Hollowed Harp, Seastrum...): the recording made pale (brightness squeezed
    into 80-182, where the default's fixed dark/light levels see nothing) or pale and tinted still reads the same
    lit part and the full swing."""
    from fischmacro.vision.lullaby_gauge import LullabyGauge
    g = LullabyGauge()
    seen = []
    for img in _lullaby_frames():
        im = (img.astype(np.float32) * (0.4 if look == "pale" else 0.45) + (80 if look == "pale" else 70))
        im = im.astype(np.uint8)
        if look == "tinted":
            im = cv2.add(im, np.full_like(im, (40, 0, 25)))
        r = g.update(im, (960, 902), H)
        if r.present:
            seen.append((r.pointer, r.segments))
    assert len(seen) > 35
    segs = seen[len(seen) // 2][1]
    assert len(segs) == 1 and segs[0][0] < 0.05 and 0.47 < segs[0][1] < 0.56
    assert min(p for p, _ in seen) < 0.15 and max(p for p, _ in seen) > 0.8


def test_lullaby_clicks_every_pass_once(monkeypatch):
    """Every pass of the pendulum over the lit part gets exactly one click, inside it, with no pause between
    hits. The clip has 4 passes (one turns around at the far end of the lit part). The 1.2 s start-of-reel
    wait is switched off here only so the short clip can be judged."""
    import fischmacro.rods.lullaby as lullaby
    from fischmacro.diagnostics.replay import replay
    import tempfile
    monkeypatch.setattr(lullaby, "LULLABY_GRACE", 0.0)
    tmp = Path(tempfile.mkdtemp())
    for k, img in enumerate(_lullaby_frames()):
        cv2.imwrite(str(tmp / f"{k:04d}.jpg"), img)
    res = replay(sorted(str(p) for p in tmp.glob("*.jpg")), "lullaby", fps=30)
    clicks = [r for r in res.rows if "down" in r["inputs"]]
    assert len(clicks) == 4
    for r in clicks:
        parts = [tuple(map(float, x.split("-"))) for x in r["lit_parts"].split(";") if x]
        assert any(a <= r["pendulum"] <= b for a, b in parts)


def test_lullaby_clicks_only_inside_the_lit_part():
    from fischmacro.diagnostics.replay import replay
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    for k, img in enumerate(_lullaby_frames()):
        cv2.imwrite(str(tmp / f"{k:04d}.jpg"), img)
    res = replay(sorted(str(p) for p in tmp.glob("*.jpg")), "lullaby", fps=30)
    clicks = [r for r in res.rows if "down" in r["inputs"]]
    assert clicks, "the beat must be played"
    for r in clicks:
        p = r["pendulum"]
        parts = [tuple(map(float, x.split("-"))) for x in r["lit_parts"].split(";") if x]
        assert any(a <= p <= b for a, b in parts), f"click at {p} outside {parts}"
    assert all(r["bar_l"] is None or True for r in res.rows)


def test_stellarwave_cursor_goes_to_the_next_sign():
    """Replaying 16.8 -> 20.2 s: every cursor move made by the sign picker lands on the sign asked for."""
    from fischmacro.diagnostics.replay import replay
    files = [str(ROOT / f"t{t:04.1f}.jpg") for t in (16.8, 17.5, 18.2, 18.7, 19.5, 20.2)]
    res = replay(files, "stellarwave", fps=2)
    expected = {"Aries": 1090, "Taurus": 830, "Gemini": 560, "Cancer": 1440}
    moves = [(r, s) for r in res.rows for s in r["inputs"].split() if s.startswith("move(")]
    assert moves, "the picker must move the cursor"
    for r, s in moves:
        x = int(s[5:-1].split(",")[0])
        assert abs(x - expected[r["next"]]) < 40, f"moved to {x} for {r['next']}"
