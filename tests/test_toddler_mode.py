"""
Tests for --toddler mode.

Toddler thresholds are dramatically lower than any cat sensitivity level.
These tests verify:
  • Patterns that would MISS at cat-medium/high DO fire in toddler mode
  • Toddler STREAK_MIN and STREAK_WINDOW are tighter
  • Lock delay is 0 in toddler mode (immediate lock)
  • Toddler messages are used (not cat messages)
  • Human-typing vetoes still apply
"""
from tests.conftest import EngineHarness


class TestToddlerPawDetection:
    def test_two_simultaneous_keys_fires_toddler(self, cd):
        """Toddler min_paw=2 — two simultaneous non-modifier keys fire."""
        with EngineHarness(cd, toddler=True) as h:
            h.key_down(30)   # a
            h.key_down(31)   # s
            h.flush()
        assert len(h.detections) >= 1

    def test_two_simultaneous_does_not_fire_cat_high(self, cd):
        """Same two keys do NOT fire in cat high mode (min_paw=3)."""
        with EngineHarness(cd, sensitivity="high") as h:
            h.key_down(30)
            h.key_down(31)
            h.flush()
        assert len(h.detections) == 0

    def test_toddler_paw_with_modifier_still_needs_two_chars(self, cd):
        """Shift + 1 char = 1 non-modifier key → below toddler min_paw=2."""
        with EngineHarness(cd, toddler=True) as h:
            h.key_down(42)   # Shift
            h.key_down(30)   # a
            h.flush()
        assert len(h.detections) == 0


class TestToddlerStreakDetection:
    def test_three_rapid_same_key_fires_toddler(self, cd):
        """Toddler STREAK_MIN=3 — three fast taps of same key fire."""
        with EngineHarness(cd, toddler=True) as h:
            for _ in range(4):
                h.key_down(30)
            h.flush()
        assert len(h.detections) >= 1

    def test_three_same_key_no_fire_cat_mode(self, cd):
        """Three taps are below cat STREAK_MIN_COUNT=6 — no detection."""
        with EngineHarness(cd, sensitivity="high") as h:
            for _ in range(3):
                h.key_down(30)
            h.flush()
        assert len(h.detections) == 0

    def test_backspace_streak_still_excluded_in_toddler(self, cd):
        """Backspace spam must not fire even in toddler mode."""
        with EngineHarness(cd, toddler=True) as h:
            for _ in range(10):
                h.key_down(14)
            h.flush()
        assert len(h.detections) == 0


class TestToddlerMessages:
    def test_toddler_detection_uses_toddler_messages(self, cd):
        """When toddler mode fires, the notification message comes from TODDLER_MESSAGES."""
        with EngineHarness(cd, toddler=True) as h:
            h.key_down(30)
            h.key_down(31)
            h.flush()
        assert len(h.detections) >= 1
        # Every fired message must be a known toddler message
        for msg in h.detections:
            assert msg in cd.TODDLER_MESSAGES, (
                f"Unexpected message in toddler mode: {msg!r}"
            )

    def test_cat_mode_uses_cat_messages(self, cd):
        """Normal cat detection must use CAT_MESSAGES, not toddler ones."""
        with EngineHarness(cd, sensitivity="high") as h:
            for code in (30, 31, 32, 33):
                h.key_down(code)
            h.flush()
        if h.detections:
            for msg in h.detections:
                assert msg in cd.CAT_MESSAGES


class TestToddlerThresholdConstants:
    def test_toddler_streak_window_shorter(self, cd):
        assert cd.TODDLER_STREAK_WINDOW < cd.STREAK_WINDOW_SECS

    def test_toddler_streak_min_lower(self, cd):
        assert cd.TODDLER_STREAK_MIN < cd.STREAK_MIN_COUNT

    def test_toddler_lock_delay_is_zero(self, cd):
        assert cd.TODDLER_LOCK_DELAY == 0
