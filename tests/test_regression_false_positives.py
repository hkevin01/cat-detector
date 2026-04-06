"""
Regression tests — false-positive guard.

These tests verify that plausible human typing patterns NEVER trigger the
detector.  A single false positive here is a critical failure.

Patterns tested:
  • Fast but rhythmic home-row typing (120 WPM)
  • Ctrl+Shift+Alt hotkeys (window managers, IDEs)
  • Holding arrow keys (text navigation)
  • Holding backspace (deleting a line)
  • Repeated-character words ("llll" in "llllama" — still below threshold)
  • Password entry (random chars but sequential, not simultaneous)
"""
import time
import pytest

from tests.conftest import EngineHarness

# Simulate "the quick brown fox" in evdev keycodes — always release before next press
_HUMAN_TYPING = [
    20, 15, 18,  # t h r — top row left
    34, 49, 34,  # g n g — middle/bottom
    30, 31, 32,  # a s d — home row
    30, 31, 32,  # repeated home row (natural rhythm)
    18, 32, 34,  # r d n
    14, 14, 14,  # backspace × 3 — correction
]

# Sequential typing: 16 home-row keys (well below min_keys=18/24) → never fires walk
# Keys are released before the next is pressed (strict sequential, never simultaneous)
_FAST_SEQ = [30, 31, 32, 33, 34, 35, 36, 37, 38, 30, 31, 32, 33, 34, 35, 36]


class TestHumanTypingNeverFires:
    def test_home_row_typing_no_detection(self, cd):
        """Home-row sequential typing must never trigger."""
        with EngineHarness(cd, sensitivity="high") as h:
            for code in _HUMAN_TYPING:
                h.key_down(code)
                h.key_up(code)    # always release — sequential, never simultaneous
                time.sleep(0.06)  # ~17 keys/s — fast human
            h.flush()
        assert len(h.detections) == 0

    def test_sequential_keys_no_detection(self, cd):
        """16 home-row sequential keys (below min_keys) must not fire walk."""
        with EngineHarness(cd, sensitivity="medium") as h:
            for code in _FAST_SEQ:
                h.key_down(code)
                h.key_up(code)       # strict sequential — never simultaneous
                time.sleep(0.07)     # ~14 keys/s — human rhythm
            h.flush()
        assert len(h.detections) == 0

    def test_hold_backspace_no_detection(self, cd):
        """Holding backspace to delete a whole line must not fire."""
        with EngineHarness(cd, sensitivity="high") as h:
            for _ in range(40):
                h.key_down(14)
                h.key_hold(14)
                time.sleep(0.03)
            h.flush()
        assert len(h.detections) == 0

    def test_ctrl_shift_hotkey_no_detection(self, cd):
        """Ctrl + Shift + letter chord is a hotkey, not a cat."""
        with EngineHarness(cd, sensitivity="high") as h:
            h.key_down(29)   # Ctrl
            h.key_down(42)   # Shift
            h.key_down(33)   # G
            h.flush()
        assert len(h.detections) == 0

    def test_arrow_key_navigation_no_detection(self, cd):
        """Holding up/down arrow for scrolling must not fire."""
        with EngineHarness(cd, sensitivity="high") as h:
            for _ in range(30):
                h.key_hold(103)   # KEY_UP
                time.sleep(0.03)
            h.flush()
        assert len(h.detections) == 0

    def test_password_entry_no_detection(self, cd):
        """
        Random-looking characters typed sequentially (password) must not fire.
        Even at high sensitivity, sequential-only entry stays below paw threshold.
        """
        # Random-ish but sequential keypresses — no simultaneous holds
        pwd_keys = [16, 30, 19, 49, 24, 38, 31, 45, 23, 17, 36, 44]
        with EngineHarness(cd, sensitivity="high") as h:
            for code in pwd_keys:
                h.key_down(code)
                h.key_up(code)
                time.sleep(0.15)   # slow deliberate typing
            h.flush()
        assert len(h.detections) == 0

    def test_three_simultaneous_keys_no_detection_at_low(self, cd):
        """3 simultaneous keys is below min_paw=5 at low sensitivity."""
        with EngineHarness(cd, sensitivity="low") as h:
            h.key_down(30)
            h.key_down(31)
            h.key_down(32)
            h.flush()
        assert len(h.detections) == 0
