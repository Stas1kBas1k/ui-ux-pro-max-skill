"""Live performance of the threaded engine on the built-in test game (no Roblox needed).

    python -m fischmacro.simulation.perf --seconds 20

Reports frame rate, per-frame capture + vision time, CPU use of the whole process, peak memory and how
long the engine takes to start. Simulation capture renders frames in Python, so real screen capture on
Windows has a different (usually lower) capture cost.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time


def measure(seconds: float = 20.0) -> dict:
    import resource

    t0 = time.perf_counter()
    from fischmacro.automation.engine import AutomationEngine
    from fischmacro.profiles.schema import AppSettings, Profile
    s = AppSettings()
    s.capture.mode = "simulation"
    eng = AutomationEngine(s, Profile())
    init_ms = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    eng.start_automation()
    start_ms = (time.perf_counter() - t1) * 1000
    cpu0, wall0 = time.process_time(), time.perf_counter()
    fps, cap, proc, reel_proc = [], [], [], []
    last_id = -1
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        time.sleep(0.05)
        snap = eng.snapshot()
        if snap.frame_id != last_id:
            last_id = snap.frame_id
            fps.append(snap.fps)
            cap.append(snap.capture_ms)
            proc.append(snap.process_ms)
            if snap.fsm_state == "REELING":
                reel_proc.append(snap.capture_ms + snap.process_ms)
    cpu = (time.process_time() - cpu0) / (time.perf_counter() - wall0) * 100
    catches = eng.session.catches
    eng.shutdown()
    mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    def p(xs, q):
        return round(sorted(xs)[min(len(xs) - 1, int(q * len(xs)))], 2) if xs else 0.0
    return {
        "seconds": seconds, "catches": catches,
        "engine_init_ms": round(init_ms), "start_ms": round(start_ms),
        "frames_per_second_median": round(statistics.median(fps), 1) if fps else 0,
        "capture_ms_p50": p(cap, 0.5), "vision_ms_p50": p(proc, 0.5), "vision_ms_p95": p(proc, 0.95),
        "reeling_frame_latency_ms_p50": p(reel_proc, 0.5), "reeling_frame_latency_ms_p95": p(reel_proc, 0.95),
        "cpu_percent_of_one_core": round(cpu), "peak_memory_mb": round(mem_mb),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=20.0)
    a = ap.parse_args()
    print(json.dumps(measure(a.seconds), indent=2))


if __name__ == "__main__":
    main()
