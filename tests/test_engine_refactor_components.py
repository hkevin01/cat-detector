"""
Tests for pure scoring components and structured event records.
"""

import json
from datetime import datetime, timezone


def test_adaptive_baseline_never_drops_below_static(cd):
    cal = cd.AdaptiveBaselineCalibrator(static_min=1.03, warmup=5)
    for s in (0.4, 0.5, 0.6, 0.55, 0.58, 0.61):
        cal.observe(s)
    assert cal.threshold() >= 1.03


def test_adaptive_baseline_shifts_up_conservatively(cd):
    cal = cd.AdaptiveBaselineCalibrator(static_min=1.00, warmup=5, margin=0.05, max_shift=0.15)
    for _ in range(20):
        cal.observe(1.20)
    thr = cal.threshold()
    assert 1.00 <= thr <= 1.15


def test_record_detection_event_writes_jsonl(cd, tmp_path):
    rec = cd.DetectionRecord(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        entity="cat",
        reason="walking",
        sensitivity="medium",
        toddler_mode=False,
        metrics={"keys": 24, "rate": "12.0/s", "spread": "67%"},
        walk_score=1.08,
        walk_threshold=1.03,
    )

    out_file = tmp_path / "detections.jsonl"

    def _path_override():
        return out_file

    old = cd._event_log_path
    cd._event_log_path = _path_override
    try:
        cd.record_detection_event(rec)
    finally:
        cd._event_log_path = old

    payload = json.loads(out_file.read_text(encoding="utf-8").strip())
    assert payload["reason"] == "walking"
    assert payload["walk_score"] == 1.08


def test_compute_walk_metrics_returns_consistent_shape(cd):
    key_times = {30: [1.0, 2.0], 31: [2.1]}
    # engine stores deques; lists also support this limited shape for the helper
    from collections import deque

    key_times = {k: deque(v) for k, v in key_times.items()}
    active, metrics = cd.compute_walk_metrics(key_times, now=2.2)
    assert isinstance(active, set)
    assert metrics.unique_keys >= 1
    assert 0.0 <= metrics.spread <= 1.0
