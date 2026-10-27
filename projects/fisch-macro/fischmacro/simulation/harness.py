"""Deterministic closed-loop simulation: simulated game -> vision -> FSM -> input.

Used by the tests and runnable from the command line to evaluate tuning::

    python -m fischmacro.simulation.harness --cycles 20 --difficulty 0.5
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass, field

from fischmacro.automation.fsm import FishingStateMachine, State
from fischmacro.input.controller import InputController
from fischmacro.profiles.schema import Profile
from fischmacro.simulation.game import SimulatedFischGame, SimulatedInputBackend
from fischmacro.vision.engine import VisionEngine
from fischmacro.vision.frame import Frame


@dataclass
class SimResult:
    cycles: list[dict] = field(default_factory=list)
    events: list[tuple[str, str]] = field(default_factory=list)
    game: SimulatedFischGame | None = None
    fsm: FishingStateMachine | None = None
    sim_time: float = 0.0

    @property
    def outcomes(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.cycles:
            out[c["outcome"]] = out.get(c["outcome"], 0) + 1
        return out


def run_simulation(profile: Profile | None = None, *, seed: int = 0, difficulty: float = 0.4,
                   cycles: int = 5, max_time: float = 600.0, fps: float = 40.0, noise: float = 0.0,
                   width: int = 1280, height: int = 720, roi: bool = True,
                   game: SimulatedFischGame | None = None, on_step=None) -> SimResult:
    profile = copy.deepcopy(profile or Profile())
    game = game or SimulatedFischGame(width, height, seed=seed, difficulty=difficulty, noise=noise)
    result = SimResult(game=game)
    inputs = InputController(SimulatedInputBackend(game), click_hold_ms=0, key_hold_ms=0, mouse_nudge=False)
    engine = VisionEngine(profile)

    def emit(kind, msg, **data):
        result.events.append((kind, msg))
        if kind == "cycle":
            result.cycles.append(dict(data))

    # Sleeps inside module routines advance simulated time instead of blocking.
    fsm = FishingStateMachine(profile, inputs, emit=emit, sleep=lambda s: game.step(s))
    result.fsm = fsm
    dt = 1.0 / fps
    fsm.start(game.t)
    while game.t < max_time and len(result.cycles) < cycles and fsm.running:
        wanted = engine.regions_for(fsm.state.value)
        frame = Frame(game.render(), (game.width, game.height), timestamp=game.t)
        obs = engine.process(frame, wanted, fsm.state.value)
        fsm.update(obs, game.t)
        if on_step:
            on_step(game, fsm, obs)
        # integrate the game at a finer step than the vision rate
        for _ in range(3):
            game.step(dt / 3)
    result.sim_time = game.t
    fsm.stop(game.t, "simulation finished")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the closed-loop fishing simulation.")
    ap.add_argument("--cycles", type=int, default=10)
    ap.add_argument("--difficulty", type=float, default=0.4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fps", type=float, default=40)
    ap.add_argument("--noise", type=float, default=0.0)
    args = ap.parse_args()
    res = run_simulation(seed=args.seed, difficulty=args.difficulty, cycles=args.cycles, fps=args.fps, noise=args.noise)
    g = res.game
    print(f"simulated {res.sim_time:.0f}s  outcomes={res.outcomes}  game={g.stats}")
    print(f"final state={res.fsm.state.value}")


if __name__ == "__main__":
    main()
