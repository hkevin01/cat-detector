"""
Integration tests — _detection_engine end-to-end with synthetic key streams.

Every test drives the full engine (running in a daemon thread) through the
EngineHarness.  A detection fires → notify() is called → harness records it.
Tests assert 0 or ≥1 detections within a short flush window.
"""
import time

from tests.conftest import EngineHarness


# ── helper: build key sequences ──────────────────────────────────────────

# Evdev keycodes for letters a–z: 30–55
_ALPHA = list(range(30, 56))

# "cat walk" — 24 unique character keys across multiple zones
# Spread across top-left, top-right, home-*, bottom-* zones
_CAT_WALK_KEYS = [
    2,3,4,5,6,7,8,9,10,11,     # digit row
    16,17,18,19,20,21,22,23,   # QWERTY top row
    30,31,32,33,34,35,36,37,   # home row
]  # 26 unique keys — above medium threshold (24)

_BORDERLINE_WALK_KEYS = [
    2, 3, 4, 5,          # top-left
    6, 7, 21, 22,        # top-center
    8, 9, 10, 11,        # top-right
    35, 36, 37, 38,      # home-right
    33, 34, 47, 48,      # home-center
    30, 31, 32, 44,      # home-left
]  # 24 unique keys with broad spread but low far-hop transitions


# ── PAW PRESS detection ──────────────────────────────────────────────────

class TestPawPressDetection:
    def test_cat_paw_high_sensitivity(self, cd):
        """4 simultaneous non-modifier keys → fire at 'high' (min_paw=3)."""
        with EngineHarness(cd, sensitivity="high") as h:
            for code in (30, 31, 32, 33):   # a s d f
                h.key_down(code)
            h.flush()
        assert len(h.detections) >= 1

    def test_cat_paw_medium_sensitivity(self, cd):
        """5 simultaneous keys → fire at 'medium' (min_paw=4)."""
        with EngineHarness(cd, sensitivity="medium") as h:
            for code in (30, 31, 32, 33, 34):   # a s d f g
                h.key_down(code)
            h.flush()
        assert len(h.detections) >= 1

    def test_modifier_keys_excluded_from_paw_count(self, cd):
        """Shift + 2 chars should NOT fire at medium (min_paw=4)."""
        with EngineHarness(cd, sensitivity="medium") as h:
            h.key_down(42)   # KEY_LEFTSHIFT
            h.key_down(30)   # a
            h.key_down(31)   # s
            h.key_down(32)   # d
            h.flush()
        # Only 3 non-modifier keys — below min_paw=4 for medium
        assert len(h.detections) == 0

    def test_human_hold_keys_excluded_from_paw_count(self, cd):
        """Backspace + 3 chars does NOT fire at medium."""
        with EngineHarness(cd, sensitivity="medium") as h:
            h.key_down(14)   # KEY_BACKSPACE
            h.key_down(30)
            h.key_down(31)
            h.key_down(32)
            h.flush()
        assert len(h.detections) == 0

    def test_enter_plus_two_chars_fires(self, cd):
        """Enter + 2 simultaneous char keys = dangerous paw → always fires."""
        with EngineHarness(cd, sensitivity="low") as h:
            h.key_down(28)   # Enter
            h.key_down(30)   # a
            h.key_down(31)   # s
            h.flush()
        assert len(h.detections) >= 1

    def test_enter_alone_does_not_fire(self, cd):
        """Enter alone is never a cat."""
        with EngineHarness(cd, sensitivity="high") as h:
            h.key_down(28)
            h.flush()
        assert len(h.detections) == 0


# ── STREAK detection ─────────────────────────────────────────────────────

class TestStreakDetection:
    def test_six_rapid_same_key_fires(self, cd):
        """6× same key in <1 s → STREAK detection."""
        with EngineHarness(cd, sensitivity="medium") as h:
            for _ in range(7):
                h.key_down(30)   # 'a' seven times
            h.flush()
        assert len(h.detections) >= 1

    def test_five_rapid_same_key_no_fire_default(self, cd):
        """5× same key is below STREAK_MIN_COUNT=6 → no detection."""
        with EngineHarness(cd, sensitivity="medium") as h:
            for _ in range(5):
                h.key_down(30)
                time.sleep(0.01)
            h.flush()
        assert len(h.detections) == 0

    def test_backspace_streak_never_fires(self, cd):
        """Humans hold backspace — rapid repeats must never fire."""
        with EngineHarness(cd, sensitivity="high") as h:
            for _ in range(20):
                h.key_down(14)   # KEY_BACKSPACE
            h.flush()
        assert len(h.detections) == 0

    def test_space_streak_never_fires(self, cd):
        """Gamers hold space for dash/jump — must not fire."""
        with EngineHarness(cd, sensitivity="high") as h:
            for _ in range(20):
                h.key_down(57)   # KEY_SPACE
            h.flush()
        assert len(h.detections) == 0


# ── WALK / BURST detection ───────────────────────────────────────────────

class TestWalkDetection:
    def test_cat_walk_fires_at_medium(self, cd):
        """26 unique keys at rapid rate → walk detection at medium."""
        with EngineHarness(cd, sensitivity="medium") as h:
            # Send all keys with tiny gaps — inside WINDOW_SECS=2s
            for code in _CAT_WALK_KEYS:
                h.key_down(code)
                h.key_up(code)
                time.sleep(0.01)
            h.flush(0.4)
        assert any(rec.reason == "walking" for rec in h.records)

    def test_single_borderline_walk_window_does_not_fire(self, cd):
        """One borderline walk window should not fire without temporal confirmation."""
        with EngineHarness(cd, sensitivity="medium") as h:
            for code in _BORDERLINE_WALK_KEYS:
                h.key_down(code)
                h.key_up(code)
                time.sleep(0.01)
            h.flush(0.35)
        assert not any(rec.reason == "walking" for rec in h.records)

    def test_walk_vetoed_by_backspace(self, cd):
        """Backspace anywhere in the walk window vetoes the cat trigger."""
        with EngineHarness(cd, sensitivity="high") as h:
            for code in _CAT_WALK_KEYS[:15]:
                h.key_down(code)
                h.key_up(code)     # release before pressing next key
                time.sleep(0.005)
            h.key_down(14)         # KEY_BACKSPACE — veto signal
            h.key_up(14)
            for code in _CAT_WALK_KEYS[15:]:
                h.key_down(code)
                h.key_up(code)
                time.sleep(0.005)
            h.flush(0.4)
        # Walk detector cannot fire because HUMAN_HOLD_KEYS(backspace) in window
        assert len(h.detections) == 0


class TestZoneHopDetection:
    def test_zone_hopping_fires_for_cat_like_pattern(self, cd):
        """Rapid non-adjacent zone hops should trigger zone-hopping detection."""
        # Alternate between distant zones to emulate paw movement.
        pattern = [
            2,   # top-left
            10,  # top-right
            44,  # bottom-left
            51,  # home-right / bottom-right overlap
            16,  # top-left
            38,  # top-right
            46,  # bottom-left
            53,  # bottom-right
        ]
        with EngineHarness(cd, sensitivity="medium") as h:
            for code in pattern:
                h.key_down(code)
                time.sleep(0.02)
            h.flush(0.3)
        assert len(h.detections) >= 1

    def test_adjacent_zone_alternation_does_not_trigger(self, cd):
        """Near-home human movement should stay below zone-hopping thresholds."""
        # Home-left to home-center alternation only.
        pattern = [30, 31, 33, 34, 30, 33, 31, 34, 30, 33]
        with EngineHarness(cd, sensitivity="medium") as h:
            for code in pattern:
                h.key_down(code)
                h.key_up(code)
                time.sleep(0.04)
            h.flush(0.3)
        assert len(h.detections) == 0


class TestHoldSitDetection:
    def test_single_key_flood_fires(self, cd):
        """15+ hold events for one key within 2 s → sit detection."""
        with EngineHarness(cd, sensitivity="medium") as h:
            for _ in range(16):
                h.key_hold(30)   # 'a' auto-repeating
            h.flush()
        assert len(h.detections) >= 1

    def test_multi_key_hold_fires(self, cd):
        """2 keys each with 5+ hold events → multi-cat-weight detection."""
        with EngineHarness(cd, sensitivity="medium") as h:
            for _ in range(6):
                h.key_hold(30)
                h.key_hold(31)
            h.flush()
        assert len(h.detections) >= 1

    def test_arrow_key_hold_never_fires(self, cd):
        """Humans hold arrow keys — must never trigger."""
        with EngineHarness(cd, sensitivity="high") as h:
            for _ in range(30):
                h.key_hold(108)   # KEY_DOWN
            h.flush()
        assert len(h.detections) == 0

    def test_backspace_hold_never_fires(self, cd):
        """Humans hold backspace forever — must never trigger."""
        with EngineHarness(cd, sensitivity="high") as h:
            for _ in range(30):
                h.key_hold(14)
            h.flush()
        assert len(h.detections) == 0


# ── COOLDOWN ─────────────────────────────────────────────────────────────

class TestCooldown:
    def test_second_detection_suppressed_during_cooldown(self, cd):
        """Two burst sequences in quick succession → only one detection fires."""
        with EngineHarness(cd, sensitivity="high") as h:
            # First burst — should fire
            for _ in range(8):
                h.key_down(30)
            h.flush(0.1)
            first_count = len(h.detections)
            # Immediately send another burst (still inside 45 s cooldown)
            for _ in range(8):
                h.key_down(30)
            h.flush(0.1)
        assert first_count == 1
        assert len(h.detections) == 1
