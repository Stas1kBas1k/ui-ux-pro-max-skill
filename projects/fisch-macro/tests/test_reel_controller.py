from fischmacro.automation.reel_controller import ReelController
from fischmacro.profiles.schema import ReelConfig


def run(ctrl, fish, left, right, n=30, t0=0.0, dt=1 / 40, **kw):
    holds = []
    for i in range(n):
        holds.append(ctrl.update(fish, left, right, t0 + i * dt, **kw))
    return holds


def test_holds_when_fish_is_right_of_bar():
    holds = run(ReelController(ReelConfig()), fish=0.8, left=0.3, right=0.5)
    assert sum(holds) / len(holds) > 0.9


def test_releases_when_fish_is_left_of_bar():
    holds = run(ReelController(ReelConfig()), fish=0.2, left=0.5, right=0.7)
    assert sum(holds) / len(holds) < 0.1


def test_centered_fish_gives_hover_duty():
    cfg = ReelConfig(hold_bias=0.5)
    holds = run(ReelController(cfg), fish=0.5, left=0.4, right=0.6, n=200)
    duty = sum(holds) / len(holds)
    assert 0.4 <= duty <= 0.6


def test_hover_duty_follows_hold_bias():
    cfg = ReelConfig(hold_bias=0.3)
    holds = run(ReelController(cfg), fish=0.5, left=0.4, right=0.6, n=200)
    assert 0.2 <= sum(holds) / len(holds) <= 0.4


def test_derivative_reacts_to_fish_velocity():
    cfg = ReelConfig()
    moving = ReelController(cfg)
    # fish centred now but moving right quickly -> controller should push right more than hover
    for i in range(20):
        moving.update(0.30 + i * 0.01, 0.20 + i * 0.01 - 0.0, 0.40 + i * 0.01, i / 40)
    assert moving.debug.fish_v > 0.3
    assert moving.debug.duty > cfg.hold_bias


def test_edge_rules():
    c = ReelController(ReelConfig(edge_margin=0.08))
    c.update(0.03, 0.0, 0.2, 0.0)
    assert c.debug.reason == "edge-left" and not c.debug.hold
    c = ReelController(ReelConfig(edge_margin=0.08))
    c.update(0.97, 0.8, 1.0, 0.0)
    assert c.debug.reason == "edge-right" and c.debug.hold


def test_low_confidence_releases():
    c = ReelController(ReelConfig(min_confidence=0.5))
    assert not c.update(0.9, 0.2, 0.4, 0.0, confidence=0.2)
    assert c.debug.reason == "low-confidence"


def test_max_continuous_hold_is_enforced():
    c = ReelController(ReelConfig(max_hold_seconds=0.5))
    holds = run(c, fish=0.95, left=0.1, right=0.3, n=60, dt=0.02)  # 1.2 s of "hold"
    # at least one forced release must occur within the 1.2 s window
    assert not all(holds)
    assert any(c_ for c_ in holds)


def test_velocity_spikes_are_clamped():
    c = ReelController(ReelConfig(smoothing=0.0))
    c.update(0.1, 0.4, 0.6, 0.0)
    c.update(0.9, 0.4, 0.6, 0.0001)  # absurd jump in 0.1 ms
    assert abs(c.debug.fish_v) <= 5.0


def test_hover_estimator_recovers_true_duty():
    from fischmacro.automation.reel_controller import HoverEstimator
    import random
    rnd = random.Random(1)
    est = HoverEstimator()
    k, true_hover = 3.0, 0.3  # a = k * (hold - hover) + noise
    for _ in range(600):
        h = 1.0 if rnd.random() < 0.5 else 0.0
        est.add(h, k * (h - true_hover) + rnd.gauss(0, 1.0))
    assert est.value is not None and abs(est.value - true_hover) < 0.06


def test_hover_estimator_needs_both_input_states():
    from fischmacro.automation.reel_controller import HoverEstimator
    est = HoverEstimator()
    for _ in range(200):
        est.add(1.0, 2.0)  # only ever held: no information about the release side
    assert est.value is None


def test_auto_hover_off_uses_configured_bias():
    c = ReelController(ReelConfig(auto_hover=False, hold_bias=0.4))
    c.hover.value = 0.8
    c.update(0.5, 0.4, 0.6, 0.0)
    assert c.debug.hover == 0.4 and not c.debug.hover_learned


def test_plant_model_learns_bar_physics():
    from fischmacro.automation.reel_controller import PlantModel
    import random
    rnd = random.Random(2)
    m = PlantModel()
    alpha, beta, gamma = 4.8, -2.4, -1.2
    v = 0.0
    for _ in range(800):
        h = float(rnd.random() < 0.5)
        a = alpha * h + beta + gamma * v
        m.add(h, v, a + rnd.gauss(0, 0.5))
        v = max(-2, min(2, v + a * 0.025))
    la, lb, lg = m.params
    assert abs(la - alpha) < 0.4 and abs(lb - beta) < 0.3 and abs(lg - gamma) < 0.4


def test_precision_mode_plans_toward_fish():
    cfg = ReelConfig(mode="precision")
    c = ReelController(cfg)
    c.plant.params = (4.8, -2.4, -1.2)
    assert c.update(0.8, 0.3, 0.45, 0.0)       # fish far right of a small bar: hold
    assert c.debug.reason == "mpc"
    c2 = ReelController(cfg)
    c2.plant.params = (4.8, -2.4, -1.2)
    assert not c2.update(0.2, 0.55, 0.7, 0.0)  # fish far left: release


def test_precision_mode_falls_back_until_model_is_learned():
    c = ReelController(ReelConfig(mode="precision"))
    c.update(0.5, 0.4, 0.6, 0.0)
    assert c.debug.reason == "pd"
