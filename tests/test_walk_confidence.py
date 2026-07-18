"""
Tests for walk_confidence() scoring formula.

The walk score is a weighted normalized metric:
  score = 0.45 * (unique/min_keys)
        + 0.35 * (rate/min_rate)
        + 0.20 * (spread/min_spread)
"""


def test_walk_confidence_is_one_at_exact_threshold(cd):
    thresh = cd.SENSITIVITY["medium"]
    score = cd.walk_confidence(
        unique_keys=thresh["min_keys"],
        rate=thresh["min_rate"],
        spread=thresh["spread"],
        thresh=thresh,
    )
    assert abs(score - 1.0) < 1e-9


def test_walk_confidence_increases_with_stronger_signal(cd):
    thresh = cd.SENSITIVITY["medium"]
    base = cd.walk_confidence(
        unique_keys=thresh["min_keys"],
        rate=thresh["min_rate"],
        spread=thresh["spread"],
        thresh=thresh,
    )
    stronger = cd.walk_confidence(
        unique_keys=thresh["min_keys"] + 4,
        rate=thresh["min_rate"] + 2.0,
        spread=thresh["spread"] + 0.1,
        thresh=thresh,
    )
    assert stronger > base


def test_walk_confidence_respects_weighting(cd):
    thresh = cd.SENSITIVITY["high"]
    # Raise only unique-key ratio: expected contribution is 0.45 * 10%
    score = cd.walk_confidence(
        unique_keys=int(thresh["min_keys"] * 1.1),
        rate=thresh["min_rate"],
        spread=thresh["spread"],
        thresh=thresh,
    )
    assert score > 1.0


def test_walk_temporal_gate_requires_confirmation_for_borderline_scores(cd):
    threshold = 1.03

    should_fire, hits = cd.walk_temporal_gate(1.06, threshold, consecutive_hits=0)
    assert should_fire is False
    assert hits == 1

    should_fire, hits = cd.walk_temporal_gate(1.07, threshold, consecutive_hits=hits)
    assert should_fire is True
    assert hits == 0


def test_walk_temporal_gate_fires_immediately_for_strong_scores(cd):
    threshold = 1.03
    strong_score = threshold + cd.WALK_STRONG_MARGIN + 0.01

    should_fire, hits = cd.walk_temporal_gate(strong_score, threshold, consecutive_hits=0)
    assert should_fire is True
    assert hits == 0


def test_walk_temporal_gate_resets_on_subthreshold(cd):
    threshold = 1.05
    should_fire, hits = cd.walk_temporal_gate(1.01, threshold, consecutive_hits=1)
    assert should_fire is False
    assert hits == 0
