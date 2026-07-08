"""
CLI / argparse tests.

Verifies that argument defaults and flag behaviour match the specification:
    • --lock is OFF by default
    • --lock enables lock mode
  • --no-lock disables it
  • --toddler flag enables toddler mode
  • --sensitivity accepts low / medium / high
  • --pause-secs default is GRAB_SECS_DEFAULT
  • Unknown flags produce an error exit
"""
import pathlib
import subprocess
import sys

import pytest


def _parse(cd, argv):
    """Run the production argument parser with the given argv list."""
    parser = cd.build_parser()
    return parser.parse_args(argv)


class TestDefaultArgs:
    def test_lock_off_by_default(self, cd):
        args = _parse(cd, [])
        assert args.lock is False

    def test_lock_enabled_with_flag(self, cd):
        args = _parse(cd, ["--lock"])
        assert args.lock is True

    def test_no_lock_disables_lock(self, cd):
        args = _parse(cd, ["--no-lock"])
        assert args.lock is False

    def test_default_sensitivity_is_medium(self, cd):
        args = _parse(cd, [])
        assert args.sensitivity == "medium"

    def test_sound_off_by_default(self, cd):
        args = _parse(cd, [])
        assert args.sound is False

    def test_sound_enabled_with_flag(self, cd):
        args = _parse(cd, ["--sound"])
        assert args.sound is True

    def test_toddler_off_by_default(self, cd):
        args = _parse(cd, [])
        assert args.toddler is False

    def test_toddler_enabled_with_flag(self, cd):
        args = _parse(cd, ["--toddler"])
        assert args.toddler is True

    def test_pause_secs_default(self, cd):
        args = _parse(cd, [])
        assert args.pause_secs == cd.GRAB_SECS_DEFAULT

    def test_pause_secs_override(self, cd):
        args = _parse(cd, ["--pause-secs", "30"])
        assert args.pause_secs == 30

    def test_pause_secs_zero_disables(self, cd):
        args = _parse(cd, ["--pause-secs", "0"])
        assert args.pause_secs == 0


class TestSensitivityArgChoices:
    @pytest.mark.parametrize("level", ["low", "medium", "high"])
    def test_valid_sensitivity(self, cd, level):
        args = _parse(cd, ["--sensitivity", level])
        assert args.sensitivity == level

    def test_invalid_sensitivity_exits(self, cd):
        result = subprocess.run(
            [sys.executable, "cat_detector.py", "--sensitivity", "extreme"],
            capture_output=True,
            cwd=str(pathlib.Path(__file__).parent.parent),
        )
        assert result.returncode != 0


class TestHelpOutput:
    """Test parser flags using the production parser."""

    def test_help_shows_toddler_flag(self, cd):
        """The argparse help text must mention --toddler."""
        help_text = cd.build_parser().format_help()
        assert "--toddler" in help_text

    def test_no_lock_is_a_valid_flag(self, cd):
        """--no-lock must be accepted and set lock=False."""
        args = _parse(cd, ["--no-lock"])
        assert args.lock is False
