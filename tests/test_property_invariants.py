"""
Property-based invariants for scoring monotonicity and cooldown behavior.
"""

import pytest

try:
    from hypothesis import given
    from hypothesis import strategies as st
except ImportError:
    pytest.skip("hypothesis is required for property tests", allow_module_level=True)


@given(
    unique=st.integers(min_value=1, max_value=80),
    rate=st.floats(min_value=0.1, max_value=40.0, allow_nan=False, allow_infinity=False),
    spread=st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
    du=st.integers(min_value=0, max_value=20),
    dr=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    ds=st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
)
def test_walk_confidence_monotonic(cd, unique, rate, spread, du, dr, ds):
    thresh = cd.SENSITIVITY["medium"]
    base = cd.walk_confidence(unique, rate, spread, thresh)
    stronger = cd.walk_confidence(unique + du, rate + dr, min(1.0, spread + ds), thresh)
    assert stronger >= base


@given(
    last=st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    delta1=st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    delta2=st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
)
def test_cooldown_monotonicity(cd, last, delta1, delta2):
    t1 = last + min(delta1, delta2)
    t2 = last + max(delta1, delta2)
    a1 = cd.cooldown_allows(t1, last)
    a2 = cd.cooldown_allows(t2, last)
    if a1:
        assert a2
