"""Timing benchmark: where a fishing cycle spends its time, and how long vision takes per frame.

    python -m fischmacro.simulation.benchmark --cycles 30 --json out.json

Bite and reel times come from the simulated game; the parts the macro controls (casting, the wait
after a catch, finishing the reel, recoveries) and the vision latency are what this measures.
"""
from __future__ import annotations

import argparse
import json
import statistics

from fischmacro.profiles.schema import Profile
from fischmacro.simulation.harness import run_simulation


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def benchmark(cycles: int = 30, seeds: int = 3, profile: Profile | None = None, result_seconds: float = 1.2) -> dict:
    per_state: dict[str, float] = {}
    n_cycles = 0
    total_time = 0.0
    ok = 0
    vision: dict[str, list[float]] = {}
    acquire: list[float] = []  # seconds from the reel appearing in the game to the fish being tracked

    def on_step(game, fsm, obs, mark={}):  # noqa: B006 - per-run scratch
        if game.state == "reel":
            mark.setdefault("t", game.state_t)
            if obs.reel.fish_found and not mark.get("done"):
                acquire.append(game.t - mark["t"])
                mark["done"] = True
        else:
            mark.clear()

    for seed in range(seeds):
        from fischmacro.simulation.game import SimulatedFischGame
        game = SimulatedFischGame(1280, 720, seed=seed, difficulty=0.4)
        game.result_seconds = result_seconds  # how long the game ignores clicks after a catch
        res = run_simulation(profile or Profile(), game=game, cycles=cycles, max_time=cycles * 60, fps=40,
                             on_step=on_step)
        n_cycles += len(res.cycles)
        ok += res.outcomes.get("success", 0)
        total_time += res.sim_time
        for k, v in res.fsm.time_in_state.items():
            per_state[k] = per_state.get(k, 0.0) + v
        for st, ms in res.process_ms:
            vision.setdefault(st, []).append(ms)
    n = max(1, n_cycles)
    all_ms = [m for v in vision.values() for m in v]
    return {
        "cycles": n_cycles, "catches": ok,
        "seconds_per_cycle": round(total_time / n, 2),
        "catches_per_hour": round(ok / max(1e-9, total_time) * 3600, 1),
        "state_seconds_per_cycle": {k: round(v / n, 2) for k, v in sorted(per_state.items())},
        "fish_acquire_s": {"p50": round(_pct(acquire, 0.5), 3), "p95": round(_pct(acquire, 0.95), 3)},
        "vision_ms": {"p50": round(_pct(all_ms, 0.5), 2), "p95": round(_pct(all_ms, 0.95), 2),
                      **{f"{k}_p50": round(statistics.median(v), 2) for k, v in sorted(vision.items())}},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cycles", type=int, default=30)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--result-seconds", type=float, default=1.2)
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    out = benchmark(a.cycles, a.seeds, result_seconds=a.result_seconds)
    print(json.dumps(out, indent=2))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
