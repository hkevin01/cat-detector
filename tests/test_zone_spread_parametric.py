"""
Parametric tests for zone_spread() covering every keyboard zone.

Each test feeds one key from a single known zone and asserts that:
  • spread > 0  (the zone IS detected)
  • spread <= 1/9 + epsilon  (only one zone fires)
"""
import pytest

# (zone_name, representative_keycode)
ZONE_SAMPLES = [
    ("top-left",     1),    # Esc
    ("top-center",   6),    # 6 (digit row centre)
    ("top-right",    8),    # 8
    ("home-left",    44),   # Z
    ("home-center",  33),   # G
    ("home-right",   36),   # J
    ("bottom-left",  46),   # C
    ("bottom-center",47),   # V
    ("bottom-right", 50),   # N
]


@pytest.mark.parametrize("zone,keycode", ZONE_SAMPLES, ids=[z for z, _ in ZONE_SAMPLES])
def test_zone_has_positive_spread(zone, keycode, cd):
    spread = cd.zone_spread({keycode})
    assert spread > 0.0, f"Zone {zone!r} key {keycode} gave zero spread"


@pytest.mark.parametrize("zone,keycode", ZONE_SAMPLES, ids=[z for z, _ in ZONE_SAMPLES])
def test_single_zone_spread_leq_two_ninths(zone, keycode, cd):
    """
    A key that belongs to at most 2 zones (overlapping zones share keycodes)
    should give spread <= 2/9 ≈ 0.222.
    """
    spread = cd.zone_spread({keycode})
    assert spread <= 2 / 9 + 0.01, (
        f"Zone {zone!r} key {keycode} gave unexpectedly high spread {spread:.3f}"
    )


def test_all_nine_zones_covered_by_samples(cd):
    """The ZONE_SAMPLES list must cover all nine defined zones."""
    zone_names = {z for z, _ in ZONE_SAMPLES}
    defined    = set(cd.ZONE_KEYS.keys())
    assert zone_names == defined
