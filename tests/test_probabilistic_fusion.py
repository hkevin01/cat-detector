"""
Tests for probabilistic fusion, cadence normalization, temporal memory, and
synthetic adversarial replay generators.
"""

from tests.conftest import EngineHarness


_BORDERLINE_WALK_KEYS = [
    2, 3, 4, 5,
    6, 7, 21, 22,
    8, 9, 10, 11,
    35, 36, 37, 38,
    33, 34, 47, 48,
    30, 31, 32, 44,
]


def test_bayesian_reason_posterior_monotonic_with_strength(cd):
    low = cd.bayesian_reason_posterior("walking", 0.20)
    mid = cd.bayesian_reason_posterior("walking", 0.50)
    high = cd.bayesian_reason_posterior("walking", 0.90)
    assert low < mid < high


def test_fused_posterior_risk_score_increases_with_more_signals(cd):
    weak, weak_per_reason = cd.fused_posterior_risk_score({"walking": 0.35})
    strong, strong_per_reason = cd.fused_posterior_risk_score(
        {
            "walking": 0.80,
            "zone hopping": 0.75,
            "sitting/standing": 0.70,
        }
    )
    assert weak < strong
    assert "walking" in weak_per_reason
    assert set(strong_per_reason.keys()) == {"walking", "zone hopping", "sitting/standing"}


def test_temporal_signal_memory_decay(cd):
    mem = cd.TemporalSignalMemory(half_life_secs=2.0, min_strength=0.001)
    mem.observe("walking", 1.0, now=100.0)
    near = mem.decayed_reason_strengths(now=101.0)["walking"]
    far = mem.decayed_reason_strengths(now=106.0)["walking"]
    assert near > far


def test_typing_cadence_envelope_normalizes_outlier_rates(cd):
    envelope = cd.TypingCadenceEnvelope(warmup_events=10)
    now = 100.0
    for _ in range(14):
        envelope.observe_keydown(now)
        now += 0.10

    assert abs(envelope.normalized_rate_z(10.0)) < 1e-6
    high_z = envelope.normalized_rate_z(20.0)
    assert high_z > 0.0
    boosted = cd.normalized_walk_rate(12.0, high_z)
    assert boosted > 12.0


def test_brier_score_and_reliability_bins(cd):
    pairs = [(0.90, True), (0.80, True), (0.30, False), (0.20, False)]
    score = cd.brier_score(pairs)
    bins = cd.reliability_bins(pairs, bins=5)
    assert 0.0 <= score <= 1.0
    assert len(bins) >= 1
    assert all("empirical" in row for row in bins)


def test_severity_calibration_metrics(cd):
    records = [
        {"posterior_risk_score": 0.9, "expected_positive": True},
        {"posterior_risk_score": 0.7, "expected_positive": True},
        {"posterior_risk_score": 0.4, "expected_positive": False},
        {"posterior_risk_score": 0.2, "expected_positive": False},
    ]
    metrics = cd.severity_calibration_metrics(records)
    assert metrics["count"] == 4
    assert 0.0 <= metrics["brier_score"] <= 1.0
    assert isinstance(metrics["reliability_bins"], list)


def test_synthetic_human_trace_stays_below_detection(cd):
    events = cd.generate_synthetic_near_threshold_human_trace()
    with EngineHarness(cd, sensitivity="medium", lock=False, lock_profile="adaptive") as h:
        h.replay(events)
        h.flush(0.4)
    assert len(h.detections) == 0


def test_synthetic_cat_trace_triggers_detection(cd):
    events = cd.generate_synthetic_adversarial_cat_trace()
    with EngineHarness(cd, sensitivity="medium", lock=False, lock_profile="adaptive") as h:
        h.replay(events)
        h.flush(0.5)
    assert len(h.records) >= 1
    assert any(rec.reason in {"walking", "zone hopping", "sitting/standing"} for rec in h.records)


def test_fit_reason_priors_from_replay_samples(cd):
    samples = [
        {"reason": "walking", "expected_positive": True},
        {"reason": "walking", "expected_positive": False},
        {"reason": "walking", "expected_positive": True},
        {"reason": "zone hopping", "expected_positive": False},
        {"reason": "zone hopping", "expected_positive": False},
        {"reason": "sitting/standing", "expected_positive": True},
    ]
    priors = cd.fit_reason_priors_from_replay_samples(samples)
    assert set(priors.keys()) == set(cd.FUSION_REASONS)
    assert priors["walking"] > priors["zone hopping"]
    assert 0.0 <= priors["sitting/standing"] <= 1.0


def test_tune_early_walk_posterior_threshold_from_replay(cd):
    samples = [
        {"reason": "walking", "expected_positive": True, "posterior_risk_score": 0.92},
        {"reason": "walking", "expected_positive": True, "posterior_risk_score": 0.87},
        {"reason": "walking", "expected_positive": True, "posterior_risk_score": 0.82},
        {"reason": "walking", "expected_positive": False, "posterior_risk_score": 0.71},
        {"reason": "walking", "expected_positive": False, "posterior_risk_score": 0.69},
    ]
    threshold = cd.tune_early_walk_posterior_threshold_from_replay(samples, min_precision=0.95)
    assert 0.80 <= threshold <= 0.92


def test_calibrate_fusion_from_replay_samples(cd):
    samples = [
        {"reason": "walking", "expected_positive": True, "posterior_risk_score": 0.90},
        {"reason": "walking", "expected_positive": False, "posterior_risk_score": 0.70},
        {"reason": "zone hopping", "expected_positive": True, "posterior_risk_score": 0.88},
    ]
    calibration = cd.calibrate_fusion_from_replay_samples(samples)
    assert "reason_priors" in calibration
    assert "early_walk_posterior_threshold" in calibration
    assert "calibration_metrics" in calibration
    assert calibration["sample_count"] == len(samples)


def test_engine_uses_tuned_early_walk_threshold_from_calibration(cd):
    # Lower threshold intentionally to allow single-window early-walk shortcut.
    calibration = {
        "reason_priors": {
            "walking": 0.75,
            "zone hopping": 0.40,
            "sitting/standing": 0.60,
        },
        "early_walk_posterior_threshold": 0.60,
    }

    with EngineHarness(
        cd,
        sensitivity="medium",
        lock=False,
        lock_profile="adaptive",
        fusion_calibration=calibration,
    ) as h:
        for code in _BORDERLINE_WALK_KEYS:
            h.key_down(code)
            h.key_up(code)
        h.flush(0.4)

    assert any(rec.reason == "walking" for rec in h.records)
