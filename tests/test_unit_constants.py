"""
Unit tests — module-level constants and pure helper functions.

These tests have zero I/O, no threading, and no platform dependencies.
They run in milliseconds and guard against accidental constant drift.
"""
import pytest


# ── zone_spread ──────────────────────────────────────────────────────────

class TestZoneSpread:
    def test_empty_set_returns_zero(self, cd):
        assert cd.zone_spread(set()) == 0.0

    def test_single_top_left_key(self, cd):
        # key 1 (Esc) lives in top-left zone only
        spread = cd.zone_spread({1})
        assert 0.0 < spread <= 1.0

    def test_max_spread_whole_keyboard(self, cd):
        # Supply one key from every zone — expect high spread
        one_per_zone = {1, 6, 8, 44, 33, 36, 46, 47, 50}
        spread = cd.zone_spread(one_per_zone)
        assert spread >= 0.55

    def test_return_type_is_float(self, cd):
        assert isinstance(cd.zone_spread({30}), float)

    def test_spread_bounded_0_to_1(self, cd):
        import random
        all_keys = set(range(1, 130))
        for _ in range(20):
            sample = set(random.sample(sorted(all_keys), 10))
            s = cd.zone_spread(sample)
            assert 0.0 <= s <= 1.0


# ── sensitivity constants ────────────────────────────────────────────────

class TestSensitivityConstants:
    def test_all_levels_present(self, cd):
        assert set(cd.SENSITIVITY.keys()) == {"low", "medium", "high"}

    def test_low_is_strictest(self, cd):
        lo = cd.SENSITIVITY["low"]
        hi = cd.SENSITIVITY["high"]
        assert lo["min_keys"] > hi["min_keys"]
        assert lo["min_rate"] > hi["min_rate"]
        assert lo["spread"]   > hi["spread"]
        assert lo["min_paw"]  > hi["min_paw"]

    def test_medium_between_low_and_high(self, cd):
        lo = cd.SENSITIVITY["low"]
        med = cd.SENSITIVITY["medium"]
        hi = cd.SENSITIVITY["high"]
        for field in ("min_keys", "min_rate", "spread", "min_paw"):
            assert hi[field] <= med[field] <= lo[field]

    def test_toddler_looser_than_high(self, cd):
        hi  = cd.SENSITIVITY["high"]
        tod = cd.TODDLER_SENSITIVITY
        assert tod["min_keys"] < hi["min_keys"]
        assert tod["min_rate"] < hi["min_rate"]
        assert tod["spread"]   < hi["spread"]
        assert tod["min_paw"]  < hi["min_paw"]


# ── human hold / modifier key sets ──────────────────────────────────────

class TestKeySetConstants:
    def test_backspace_in_human_hold(self, cd):
        assert 14 in cd.HUMAN_HOLD_KEYS   # KEY_BACKSPACE

    def test_delete_in_human_hold(self, cd):
        assert 111 in cd.HUMAN_HOLD_KEYS  # KEY_DELETE

    def test_arrow_keys_in_human_hold(self, cd):
        # Up, Down, Left, Right
        for code in (103, 108, 105, 106):
            assert code in cd.HUMAN_HOLD_KEYS

    def test_shift_in_modifier_keys(self, cd):
        assert 42 in cd.MODIFIER_KEYS     # KEY_LEFTSHIFT

    def test_ctrl_in_modifier_keys(self, cd):
        assert 29 in cd.MODIFIER_KEYS     # KEY_LEFTCTRL

    def test_enter_not_in_human_hold(self, cd):
        # Enter is handled specially via KEY_ENTER constant, not HUMAN_HOLD_KEYS
        assert cd.KEY_ENTER not in cd.HUMAN_HOLD_KEYS

    def test_human_hold_and_modifiers_disjoint(self, cd):
        assert not (cd.HUMAN_HOLD_KEYS & cd.MODIFIER_KEYS)


# ── ZONE_KEYS coverage ───────────────────────────────────────────────────

class TestZoneKeys:
    def test_nine_zones_defined(self, cd):
        assert len(cd.ZONE_KEYS) == 9

    def test_zone_names(self, cd):
        expected = {
            "top-left", "top-center", "top-right",
            "home-left", "home-center", "home-right",
            "bottom-left", "bottom-center", "bottom-right",
        }
        assert set(cd.ZONE_KEYS.keys()) == expected

    def test_all_zones_non_empty(self, cd):
        for zone, keys in cd.ZONE_KEYS.items():
            assert len(keys) > 0, f"Zone {zone!r} is empty"

    def test_zones_have_int_keycodes(self, cd):
        for zone, keys in cd.ZONE_KEYS.items():
            for k in keys:
                assert isinstance(k, int), f"Non-int keycode {k!r} in {zone!r}"


# ── messages ─────────────────────────────────────────────────────────────

class TestMessages:
    def test_cat_messages_non_empty(self, cd):
        assert len(cd.CAT_MESSAGES) >= 5

    def test_toddler_messages_non_empty(self, cd):
        assert len(cd.TODDLER_MESSAGES) >= 4

    def test_cat_messages_are_strings(self, cd):
        for m in cd.CAT_MESSAGES:
            assert isinstance(m, str)

    def test_toddler_messages_are_strings(self, cd):
        for m in cd.TODDLER_MESSAGES:
            assert isinstance(m, str)
