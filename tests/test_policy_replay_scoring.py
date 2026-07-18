"""
Replay-driven policy analytics tests.
"""

from tests.conftest import EngineHarness


def test_detection_records_capture_action_outcome_fields(cd, trace_loader):
    events = trace_loader("cat_walk_burst")
    with EngineHarness(cd, sensitivity="medium", lock=False, lock_profile="adaptive") as h:
        h.replay(events)
        h.flush(0.4)

    assert len(h.records) >= 1
    for rec in h.records:
        assert rec.action_outcome in {"locked", "neutralized-only"}
        assert rec.lock_profile in {
            cd.LOCK_PROFILE_ALL,
            cd.LOCK_PROFILE_HIGH_RISK,
            cd.LOCK_PROFILE_ADAPTIVE,
        }
        assert 0.0 <= rec.reason_severity <= 1.0
        assert 0.0 <= rec.posterior_risk_score <= 1.0
        assert isinstance(rec.adaptive_medium_escalated, bool)


def test_replay_policy_scoring_uses_stored_traces(cd, trace_loader):
    cat_events = trace_loader("cat_walk_burst")
    human_events = trace_loader("human_typing_edge")

    with EngineHarness(cd, sensitivity="medium", lock=False, lock_profile="adaptive") as h_cat:
        h_cat.replay(cat_events)
        h_cat.flush(0.4)

    with EngineHarness(cd, sensitivity="high", lock=False, lock_profile="adaptive") as h_human:
        h_human.replay(human_events)
        h_human.flush(0.4)

    samples = []
    for rec in h_cat.records:
        samples.append(
            {
                "reason": rec.reason,
                "expected_positive": True,
                "adaptive_medium_escalated": rec.adaptive_medium_escalated,
                "posterior_risk_score": rec.posterior_risk_score,
            }
        )
    for rec in h_human.records:
        samples.append(
            {
                "reason": rec.reason,
                "expected_positive": False,
                "adaptive_medium_escalated": rec.adaptive_medium_escalated,
                "posterior_risk_score": rec.posterior_risk_score,
            }
        )

    assert len(samples) >= 1
    scored = cd.score_policy_pairs_from_replay_samples(samples)

    for rec in h_cat.records:
        key = (rec.reason, cd.LOCK_PROFILE_ADAPTIVE)
        assert key in scored
        metric = scored[key]
        assert "precision" in metric
        assert "disruption" in metric
        assert "brier_score" in metric
        assert "reliability_bins" in metric
        assert metric["locks"] >= 0
