"""Sample-based calibration: agreement, outliers, data-dependent sample count, validation before saving."""
import numpy as np

from fischmacro.profiles.schema import Profile, Region
from fischmacro.simulation.game import SimulatedFischGame
from fischmacro.vision import autocal
from fischmacro.vision.autocal import AutoCalResult
from fischmacro.vision.calibration_session import MAX_SAMPLES, MIN_SAMPLES, CalibrationSession


def look(x=0.285, y=0.835, w=0.43, h=0.045, jitter=0.0, rng=None):
    j = (lambda: rng.normal(0, jitter)) if rng is not None else (lambda: 0.0)
    return AutoCalResult(reel=Region(x + j(), y + j(), w + j(), h + j()), bar_color="#5AC85A",
                         fish_color="#E6E6E6", confidence=0.8)


def test_agreeing_looks_finish_after_the_minimum():
    s = CalibrationSession()
    for _ in range(MIN_SAMPLES):
        s.add(look(), None)
    assert s.report.state == "validating" and s.report.samples == MIN_SAMPLES


def test_scattered_looks_need_more_samples():
    rng = np.random.default_rng(1)
    s = CalibrationSession()
    n = 0
    while s.report.state == "collecting" and n < MAX_SAMPLES:
        s.add(look(jitter=0.012, rng=rng), None)
        n += 1
    assert n > MIN_SAMPLES


def test_outliers_are_dropped_and_the_median_is_used():
    s = CalibrationSession()
    for _ in range(6):
        s.add(look(), None)
    s2 = CalibrationSession()
    for i in range(8):
        s2.add(look(x=0.6 if i == 2 else 0.285), None)  # one look caught something else
    est, inl, _ = s2.estimate()
    assert abs(est.reel.x - 0.285) < 1e-6 and len(inl) == len(s2.samples) - 1


def test_fails_with_a_reason_when_the_reel_is_never_seen():
    s = CalibrationSession()
    for _ in range(MAX_SAMPLES):
        s.add(AutoCalResult(), None)
    assert s.report.state == "failed" and "found in only 0" in s.report.reason


def test_fails_when_looks_keep_disagreeing():
    rng = np.random.default_rng(2)
    s = CalibrationSession()
    for _ in range(MAX_SAMPLES):
        s.add(look(x=rng.uniform(0.1, 0.5)), None)
    assert s.report.state == "failed" and "disagree" in s.report.reason


def _reel_frames(n=8, seed=4):
    g = SimulatedFischGame(seed=seed)
    g._start_reel()
    out = []
    for _ in range(n):
        g.step(0.12)
        out.append(g.render())
    return out


def test_validation_with_the_real_detectors_before_saving():
    frames = _reel_frames()
    s = CalibrationSession()
    for f in frames[:MIN_SAMPLES]:
        s.add(look(), f)
    assert s.report.state == "validating"
    assert s.validate(Profile()) and s.report.state == "ok", s.report.validated


def test_a_wrong_region_fails_validation_and_nothing_is_saved():
    frames = _reel_frames()
    s = CalibrationSession()
    for f in frames[:MIN_SAMPLES]:
        s.add(look(y=0.2), f)  # agreeing, but in the sky
    assert s.report.state == "validating"
    assert not s.validate(Profile())
    assert s.report.state == "failed" and "Nothing was saved" in s.report.reason


def test_end_to_end_on_simulated_frames():
    """Looks built by the real auto-calibration from rolling windows of frames."""
    g = SimulatedFischGame(seed=5)
    g._start_reel()
    g.progress_gain = g.progress_drain = 0.0
    cal = autocal.AutoCalibrator()
    s = CalibrationSession()
    t = 0.0
    while not s.done and t < 30:
        for _ in range(6):
            g.step(1 / 12)
            t += 1 / 12
            cal.add(g.render(), t)
        if len(cal.frames) >= 12:
            s.add(cal.run(), cal.full_frames[-1])
    if s.report.state == "validating":
        s.validate(Profile())
    assert s.report.state == "ok", s.report.text()
    r = s.report.result.reel
    assert abs(r.x - 0.285) < 0.02 and abs(r.w - 0.43) < 0.03
