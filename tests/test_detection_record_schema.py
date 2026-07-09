"""
Schema validation tests for structured detection JSONL payloads.
"""

import pytest


def _valid_payload(cd):
    return {
        "timestamp_utc": "2026-07-09T12:34:56.123456+00:00",
        "entity": "cat",
        "reason": "walking",
        "sensitivity": "medium",
        "toddler_mode": False,
        "metrics": {"keys": 24, "rate": "12.0/s", "spread": "66%"},
        "action_outcome": "neutralized-only",
        "lock_profile": "high-risk",
        "reason_severity": 0.77,
        "adaptive_medium_escalated": False,
        "walk_score": 1.08,
        "walk_threshold": 1.03,
    }


def test_detection_record_payload_validates(cd):
    payload = _valid_payload(cd)
    cd.validate_detection_record_payload(payload)


@pytest.mark.parametrize(
    "field",
    [
        "timestamp_utc",
        "entity",
        "reason",
        "sensitivity",
        "toddler_mode",
        "metrics",
        "action_outcome",
        "lock_profile",
        "reason_severity",
        "adaptive_medium_escalated",
        "walk_score",
        "walk_threshold",
    ],
)
def test_detection_record_missing_field_rejected(cd, field):
    payload = _valid_payload(cd)
    payload.pop(field)
    with pytest.raises(ValueError):
        cd.validate_detection_record_payload(payload)


def test_detection_record_invalid_timestamp_rejected(cd):
    payload = _valid_payload(cd)
    payload["timestamp_utc"] = "not-a-timestamp"
    with pytest.raises(ValueError):
        cd.validate_detection_record_payload(payload)


def test_detection_record_invalid_metrics_keys_rejected(cd):
    payload = _valid_payload(cd)
    payload["metrics"] = {1: "bad-key"}
    with pytest.raises(ValueError):
        cd.validate_detection_record_payload(payload)


def test_detection_record_invalid_optional_numeric_rejected(cd):
    payload = _valid_payload(cd)
    payload["walk_score"] = "1.08"
    with pytest.raises(ValueError):
        cd.validate_detection_record_payload(payload)


def test_detection_record_invalid_action_outcome_rejected(cd):
    payload = _valid_payload(cd)
    payload["action_outcome"] = "blocked"
    with pytest.raises(ValueError):
        cd.validate_detection_record_payload(payload)


def test_detection_record_invalid_reason_severity_range_rejected(cd):
    payload = _valid_payload(cd)
    payload["reason_severity"] = 1.5
    with pytest.raises(ValueError):
        cd.validate_detection_record_payload(payload)
