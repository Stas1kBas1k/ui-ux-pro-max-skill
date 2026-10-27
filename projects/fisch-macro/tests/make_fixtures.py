"""Regenerate the synthetic screenshot fixtures used by the detector tests.

    python tests/make_fixtures.py

Each PNG/JPG gets a JSON file with the ground truth taken from the simulator.
Real Fisch screenshots can be added the same way (see tests/fixtures/README.md).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fischmacro.simulation.game import SimulatedFischGame  # noqa: E402

OUT = Path(__file__).parent / "fixtures"


def save(name: str, game: SimulatedFischGame, ext: str = ".png", quality: int = 90) -> None:
    img = game.render()
    path = OUT / f"{name}{ext}"
    if ext == ".jpg":
        cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    else:
        cv2.imwrite(str(path), img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    truth = game.truth()
    truth.update(width=game.width, height=game.height)
    (OUT / f"{name}.json").write_text(json.dumps(truth, indent=2))


def reel(game: SimulatedFischGame, fish: float, bar: float, progress: float) -> None:
    game._start_reel()
    game.fish_x, game.bar_x, game.progress = fish, bar, progress


def main() -> None:
    OUT.mkdir(exist_ok=True)
    g = SimulatedFischGame(1280, 720, seed=11)
    save("idle_1280x720", g)
    reel(g, 0.62, 0.45, 0.55)
    save("reel_1280x720", g)
    save("reel_1280x720_q70", g, ".jpg", 70)
    g = SimulatedFischGame(1920, 1080, seed=12)  # 150 % DPI equivalent of 1280x720
    reel(g, 0.12, 0.05, 0.20)
    save("reel_1920x1080", g)
    g = SimulatedFischGame(640, 360, seed=13, noise=5.0)
    reel(g, 0.9, 0.68, 0.85)
    save("reel_640x360_noise", g)
    g = SimulatedFischGame(1280, 720, seed=14)
    g._set("shake")
    g.shakes_needed = 3
    g.shake_button = (0.66, 0.52)
    save("shake_1280x720", g)
    g = SimulatedFischGame(1600, 900, seed=15)
    g._set("shake")
    g.shakes_needed = 3
    g.shake_button = (0.30, 0.62)
    save("shake_1600x900", g)
    g = SimulatedFischGame(1280, 720, seed=16)
    g._set("casting")
    g.t = g.state_t + 0.7
    save("cast_1280x720", g)
    g = SimulatedFischGame(1280, 720, seed=17)
    g.disconnect()
    save("disconnect_1280x720", g)
    print("fixtures written to", OUT)


if __name__ == "__main__":
    main()
