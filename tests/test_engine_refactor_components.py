"""
Tests for pure scoring components and structured event records.
"""

import json
import os
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest


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
        action_outcome="neutralized-only",
        lock_profile="high-risk",
        reason_severity=0.71,
        adaptive_medium_escalated=False,
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


def test_write_runtime_heartbeat_writes_json(cd, tmp_path):
    out_file = tmp_path / "heartbeat.json"
    status_file = tmp_path / "status.html"

    def _path_override():
        return out_file

    def _status_override():
        return status_file

    old = cd._heartbeat_path
    old_status = cd._status_page_path
    cd._heartbeat_path = _path_override
    cd._status_page_path = _status_override
    cd._heartbeat_state["last"] = 0.0
    try:
        args = SimpleNamespace(sensitivity="medium", toddler=False, lock=True, lock_profile="adaptive")
        cd.write_runtime_heartbeat(args, force=True, last_detection_reason="walking", now_monotonic=1000.0)
    finally:
        cd._heartbeat_path = old
        cd._status_page_path = old_status

    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["heartbeat_version"] == cd.HEARTBEAT_SCHEMA_VERSION
    assert payload["last_detection_reason"] == "walking"
    assert payload["last_successful_input_event_utc"] is None
    assert payload["lock_profile"] == "adaptive"
    assert payload["lock_enabled"] is True


def test_read_runtime_status_snapshot_derives_freshness(cd, tmp_path):
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(
        json.dumps(
            {
                "timestamp_utc": "2026-07-09T12:00:00+00:00",
                "heartbeat_version": cd.HEARTBEAT_SCHEMA_VERSION,
                "pid": 1234,
                "platform": "Linux",
                "sensitivity": "medium",
                "toddler_mode": False,
                "lock_profile": "adaptive",
                "lock_enabled": True,
                "last_detection_reason": "walking",
                "last_successful_input_event_utc": "2026-07-09T12:00:05+00:00",
            }
        ),
        encoding="utf-8",
    )

    def _path_override():
        return heartbeat

    old = cd._heartbeat_path
    cd._heartbeat_path = _path_override
    try:
        status = cd.read_runtime_status_snapshot(
            now_utc=datetime.fromisoformat("2026-07-09T12:00:20+00:00")
        )
    finally:
        cd._heartbeat_path = old

    assert status["available"] is True
    assert status["freshness_label"] == "fresh"
    assert status["input_freshness_label"] == "active"
    assert status["schema_current"] is True
    assert status["last_detection_reason"] == "walking"


def test_read_runtime_status_snapshot_migrates_older_heartbeat_schema(cd, tmp_path):
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(
        json.dumps(
            {
                "timestamp_utc": "2026-07-09T12:00:00+00:00",
                "pid": 1234,
                "platform": "Linux",
                "sensitivity": "medium",
                "toddler_mode": False,
                "lock_profile": "adaptive",
                "lock_enabled": True,
                "last_detection_reason": "walking",
            }
        ),
        encoding="utf-8",
    )

    def _path_override():
        return heartbeat

    old = cd._heartbeat_path
    cd._heartbeat_path = _path_override
    try:
        status = cd.read_runtime_status_snapshot(
            now_utc=datetime.fromisoformat("2026-07-09T12:00:20+00:00")
        )
    finally:
        cd._heartbeat_path = old

    assert status["available"] is True
    assert status["heartbeat_version"] is None
    assert status["schema_current"] is False
    assert status["input_freshness_seconds"] is None
    assert status["input_freshness_label"] == "unknown"


def test_write_runtime_status_page_renders_human_readable_html(cd, tmp_path):
    heartbeat = tmp_path / "heartbeat.json"
    page = tmp_path / "status.html"
    heartbeat.write_text(
        json.dumps(
            {
                "timestamp_utc": "2026-07-09T12:00:00+00:00",
                "heartbeat_version": cd.HEARTBEAT_SCHEMA_VERSION,
                "pid": 1234,
                "platform": "Linux",
                "sensitivity": "medium",
                "toddler_mode": False,
                "lock_profile": "high-risk",
                "lock_enabled": True,
                "last_detection_reason": "zone hopping",
                "last_successful_input_event_utc": "2026-07-09T12:00:03+00:00",
            }
        ),
        encoding="utf-8",
    )

    def _heartbeat_override():
        return heartbeat

    def _page_override():
        return page

    old_heartbeat = cd._heartbeat_path
    old_page = cd._status_page_path
    cd._heartbeat_path = _heartbeat_override
    cd._status_page_path = _page_override
    try:
        cd.write_runtime_status_page()
    finally:
        cd._heartbeat_path = old_heartbeat
        cd._status_page_path = old_page

    html = page.read_text(encoding="utf-8")
    assert "cat-detector status" in html
    assert "zone hopping" in html
    assert "Heartbeat freshness" in html
    assert "Heartbeat schema version" in html
    assert "Last successful input event" in html


def test_open_raw_heartbeat_uses_default_opener(cd, tmp_path):
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text("{}", encoding="utf-8")

    def _heartbeat_override():
        return heartbeat

    called = {"count": 0}

    def _open_override(path):
        called["count"] += 1
        return path == heartbeat

    old_heartbeat = cd._heartbeat_path
    old_open = cd._open_path_with_default_app
    cd._heartbeat_path = _heartbeat_override
    cd._open_path_with_default_app = _open_override
    try:
        assert cd.open_raw_heartbeat() is True
    finally:
        cd._heartbeat_path = old_heartbeat
        cd._open_path_with_default_app = old_open

    assert called["count"] == 1


def test_compute_walk_metrics_returns_consistent_shape(cd):
    key_times = {30: [1.0, 2.0], 31: [2.1]}
    # engine stores deques; lists also support this limited shape for the helper
    from collections import deque

    key_times = {k: deque(v) for k, v in key_times.items()}
    active, metrics = cd.compute_walk_metrics(key_times, now=2.2)
    assert isinstance(active, set)
    assert metrics.unique_keys >= 1
    assert 0.0 <= metrics.spread <= 1.0


def test_dispatch_detection_actions_runs_soft_mitigation(cd):
    args = SimpleNamespace(sound=False, lock=False)
    called = {
        "notify": 0,
        "neutralize": 0,
        "sound": 0,
        "lock": 0,
    }

    old_notify = cd.notify
    old_neutralize = cd.neutralize_active_input
    old_sound = cd.play_meow
    old_lock = cd.lock_screen
    try:
        cd.notify = lambda *_a, **_kw: called.__setitem__("notify", called["notify"] + 1)
        cd.neutralize_active_input = (
            lambda *_a, **_kw: called.__setitem__("neutralize", called["neutralize"] + 1)
        )
        cd.play_meow = lambda *_a, **_kw: called.__setitem__("sound", called["sound"] + 1)
        cd.lock_screen = lambda *_a, **_kw: called.__setitem__("lock", called["lock"] + 1)

        cd.dispatch_detection_actions(args, "cat detected", "walking")
    finally:
        cd.notify = old_notify
        cd.neutralize_active_input = old_neutralize
        cd.play_meow = old_sound
        cd.lock_screen = old_lock

    assert called["notify"] == 1
    assert called["neutralize"] == 1
    assert called["sound"] == 0
    assert called["lock"] == 0


def test_dispatch_detection_actions_still_honors_lock_flag(cd):
    args = SimpleNamespace(sound=False, lock=True)
    called = {"lock": 0}
    cd.reset_lock_circuit_state()

    old_notify = cd.notify
    old_neutralize = cd.neutralize_active_input
    old_sound = cd.play_meow
    old_lock = cd.lock_screen
    try:
        cd.notify = lambda *_a, **_kw: None
        cd.neutralize_active_input = lambda *_a, **_kw: None
        cd.play_meow = lambda *_a, **_kw: None
        cd.lock_screen = lambda *_a, **_kw: called.__setitem__("lock", called["lock"] + 1)

        cd.dispatch_detection_actions(args, "cat detected", "walking")
    finally:
        cd.notify = old_notify
        cd.neutralize_active_input = old_neutralize
        cd.play_meow = old_sound
        cd.lock_screen = old_lock

    assert called["lock"] == 1


def test_high_risk_lock_profile_locks_only_for_high_risk_reason(cd):
    args = SimpleNamespace(sound=False, lock=True, lock_profile="high-risk")
    called = {"lock": 0}
    cd.reset_lock_circuit_state()

    old_notify = cd.notify
    old_neutralize = cd.neutralize_active_input
    old_sound = cd.play_meow
    old_lock = cd.lock_screen
    try:
        cd.notify = lambda *_a, **_kw: None
        cd.neutralize_active_input = lambda *_a, **_kw: None
        cd.play_meow = lambda *_a, **_kw: None
        cd.lock_screen = lambda *_a, **_kw: called.__setitem__("lock", called["lock"] + 1)

        cd.dispatch_detection_actions(args, "cat detected", "walking")
        cd.dispatch_detection_actions(args, "cat detected", "sitting/standing")
    finally:
        cd.notify = old_notify
        cd.neutralize_active_input = old_neutralize
        cd.play_meow = old_sound
        cd.lock_screen = old_lock

    assert called["lock"] == 1


def test_high_risk_lock_profile_catches_enter_simultaneous(cd):
    args = SimpleNamespace(sound=False, lock=True, lock_profile="high-risk")
    called = {"lock": 0}
    cd.reset_lock_circuit_state()

    old_notify = cd.notify
    old_neutralize = cd.neutralize_active_input
    old_sound = cd.play_meow
    old_lock = cd.lock_screen
    try:
        cd.notify = lambda *_a, **_kw: None
        cd.neutralize_active_input = lambda *_a, **_kw: None
        cd.play_meow = lambda *_a, **_kw: None
        cd.lock_screen = lambda *_a, **_kw: called.__setitem__("lock", called["lock"] + 1)

        cd.dispatch_detection_actions(args, "cat detected", "enter+simultaneous")
    finally:
        cd.notify = old_notify
        cd.neutralize_active_input = old_neutralize
        cd.play_meow = old_sound
        cd.lock_screen = old_lock

    assert called["lock"] == 1


@pytest.mark.parametrize(
    ("profile", "reason", "expected"),
    [
        ("all", "walking", True),
        ("all", "zone hopping", True),
        ("all", "paw press", True),
        ("all", "key streak", True),
        ("all", "sitting/standing", True),
        ("all", "enter+simultaneous", True),
        ("high-risk", "walking", False),
        ("high-risk", "zone hopping", False),
        ("high-risk", "paw press", False),
        ("high-risk", "key streak", False),
        ("high-risk", "sitting/standing", True),
        ("high-risk", "enter+simultaneous", True),
        ("adaptive", "walking", False),
        ("adaptive", "zone hopping", False),
        ("adaptive", "paw press", False),
        ("adaptive", "key streak", False),
        ("adaptive", "sitting/standing", True),
        ("adaptive", "enter+simultaneous", True),
    ],
)
def test_reason_profile_lock_decision_matrix(cd, profile, reason, expected):
    args = SimpleNamespace(sound=False, lock=True, lock_profile=profile)
    assert cd.should_lock_for_reason(args, reason) is expected


def test_adaptive_profile_locks_medium_only_when_escalated(cd):
    args = SimpleNamespace(sound=False, lock=True, lock_profile="adaptive")
    assert cd.should_lock_for_reason(args, "walking", adaptive_medium_escalated=False) is False
    assert cd.should_lock_for_reason(args, "walking", adaptive_medium_escalated=True) is True


def test_score_policy_pairs_from_replay_samples(cd):
    samples = [
        {"reason": "walking", "expected_positive": True, "adaptive_medium_escalated": True},
        {"reason": "walking", "expected_positive": False, "adaptive_medium_escalated": True},
        {"reason": "sitting/standing", "expected_positive": True},
    ]
    metrics = cd.score_policy_pairs_from_replay_samples(samples)

    walking_high_risk = metrics[("walking", "high-risk")]
    assert walking_high_risk["locks"] == 0
    assert walking_high_risk["precision"] is None

    walking_adaptive = metrics[("walking", "adaptive")]
    assert walking_adaptive["locks"] == 2
    assert walking_adaptive["precision"] == 0.5
    assert walking_adaptive["disruption"] == 1.0

    sit_high_risk = metrics[("sitting/standing", "high-risk")]
    assert sit_high_risk["locks"] == 1
    assert sit_high_risk["precision"] == 1.0


def test_adaptive_risk_window_escalates_repeated_medium_reason(cd):
    cal = cd.AdaptiveRiskWindowCalibrator(
        min_window_secs=5.0,
        max_window_secs=20.0,
        escalate_min_events=3,
        severity_floor=0.6,
    )
    assert cal.observe_and_should_escalate("walking", 1000.0, 0.7) is False
    assert cal.observe_and_should_escalate("walking", 1002.0, 0.75) is False
    assert cal.observe_and_should_escalate("walking", 1004.0, 0.8) is True


def test_adaptive_risk_window_keeps_high_risk_strict(cd):
    cal = cd.AdaptiveRiskWindowCalibrator()
    assert cal.observe_and_should_escalate("sitting/standing", 1000.0, 0.9) is False
    assert cal.observe_and_should_escalate("enter+simultaneous", 1001.0, 1.0) is False


def test_lock_disable_env_overrides_policy(cd):
    args = SimpleNamespace(sound=False, lock=True, lock_profile="all")
    old = os.environ.get(cd.LOCK_HARD_DISABLE_ENV)
    os.environ[cd.LOCK_HARD_DISABLE_ENV] = "1"
    try:
        assert cd.should_lock_for_reason(args, "sitting/standing") is False
        assert cd.should_lock_for_reason(args, "walking") is False
    finally:
        if old is None:
            os.environ.pop(cd.LOCK_HARD_DISABLE_ENV, None)
        else:
            os.environ[cd.LOCK_HARD_DISABLE_ENV] = old


def test_lock_circuit_blocks_repeated_locks(cd):
    cd.reset_lock_circuit_state()
    t0 = 1000.0
    assert cd.lock_circuit_allows(now=t0) is True
    assert cd.lock_circuit_allows(now=t0 + 1.0) is False


def test_lock_circuit_enforces_session_cap(cd):
    cd.reset_lock_circuit_state()
    t0 = 1000.0
    assert cd.lock_circuit_allows(now=t0) is True
    assert cd.lock_circuit_allows(now=t0 + cd.LOCK_CIRCUIT_MIN_INTERVAL_SECS + 1.0) is True
    assert cd.lock_circuit_allows(now=t0 + 2 * cd.LOCK_CIRCUIT_MIN_INTERVAL_SECS + 2.0) is False
