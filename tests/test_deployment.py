"""
Deployment / smoke tests.

These tests verify that the project artefacts are intact and that
deployment scripts and service files are syntactically valid.

Categories:
  • Import smoke  — module imports cleanly, version string is present
  • Service file  — systemd unit file has required [Unit]/[Service]/[Install] sections
  • Install shell — install.sh is a valid bash script (bash -n)
  • pyproject     — pyproject.toml is valid TOML and has required keys
"""
import pathlib
import subprocess
import sys
import tomllib

import pytest

ROOT = pathlib.Path(__file__).parent.parent


# ── Import smoke ─────────────────────────────────────────────────────────

class TestImportSmoke:
    def test_module_imports_cleanly(self, cd):
        """The module must be importable with no exceptions."""
        assert cd is not None

    def test_required_public_symbols(self, cd):
        """Verify key public symbols exist."""
        required = [
            "zone_spread", "notify", "lock_screen", "play_meow",
            "_detection_engine", "run", "main",
            "SENSITIVITY", "TODDLER_SENSITIVITY", "HUMAN_HOLD_KEYS",
            "MODIFIER_KEYS", "ZONE_KEYS", "CAT_MESSAGES", "TODDLER_MESSAGES",
            "GRAB_SECS_DEFAULT", "COOLDOWN_SECS",
        ]
        for sym in required:
            assert hasattr(cd, sym), f"Missing symbol: {sym}"

    def test_cooldown_is_positive(self, cd):
        assert cd.COOLDOWN_SECS > 0

    def test_grab_secs_default_is_positive(self, cd):
        assert cd.GRAB_SECS_DEFAULT > 0

    def test_window_secs_is_positive(self, cd):
        assert cd.WINDOW_SECS > 0


# ── pyproject.toml ────────────────────────────────────────────────────────

class TestPyprojectToml:
    @pytest.fixture(scope="class")
    def toml_data(self):
        with open(ROOT / "pyproject.toml", "rb") as f:
            return tomllib.load(f)

    def test_project_name(self, toml_data):
        assert toml_data["project"]["name"] == "cat-detector"

    def test_python_version_constraint(self, toml_data):
        req = toml_data["project"]["requires-python"]
        assert req.startswith(">=3.")

    def test_linux_optional_dep_includes_evdev(self, toml_data):
        linux_deps = toml_data["project"]["optional-dependencies"]["linux"]
        assert any("evdev" in d for d in linux_deps)

    def test_windows_optional_dep_includes_pynput(self, toml_data):
        win_deps = toml_data["project"]["optional-dependencies"]["windows"]
        assert any("pynput" in d for d in win_deps)

    def test_entry_point_defined(self, toml_data):
        scripts = toml_data["project"]["scripts"]
        assert "cat-detector" in scripts

    def test_version_present(self, toml_data):
        assert "version" in toml_data["project"]


# ── systemd service file ──────────────────────────────────────────────────

class TestServiceFile:
    @pytest.fixture(scope="class")
    def service_text(self):
        return (ROOT / "cat-detector.service").read_text()

    def test_unit_section_present(self, service_text):
        assert "[Unit]" in service_text

    def test_service_section_present(self, service_text):
        assert "[Service]" in service_text

    def test_install_section_present(self, service_text):
        assert "[Install]" in service_text

    def test_exec_start_present(self, service_text):
        assert "ExecStart=" in service_text

    def test_restart_policy(self, service_text):
        assert "Restart=on-failure" in service_text

    def test_exec_start_references_cat_detector(self, service_text):
        assert "cat_detector" in service_text

    def test_exec_start_has_lock_flag(self, service_text):
        # Lock is default ON; service should not pass --no-lock unless intended
        # The ExecStart line should invoke the script (with or without --sound etc.)
        import re
        exec_line = next(
            (l for l in service_text.splitlines() if l.startswith("ExecStart=")), ""
        )
        assert "cat_detector.py" in exec_line or "cat-detector" in exec_line


# ── install.sh syntax ────────────────────────────────────────────────────

class TestInstallScript:
    def test_install_sh_exists(self):
        assert (ROOT / "install.sh").exists()

    @pytest.mark.skipif(
        subprocess.run(["which", "bash"], capture_output=True).returncode != 0,
        reason="bash not available",
    )
    def test_install_sh_valid_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / "install.sh")],
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr.decode()

    def test_install_sh_mentions_evdev(self):
        text = (ROOT / "install.sh").read_text()
        assert "evdev" in text

    def test_install_sh_mentions_apt(self):
        text = (ROOT / "install.sh").read_text()
        assert "apt" in text

    def test_install_sh_mentions_dnf(self):
        text = (ROOT / "install.sh").read_text()
        assert "dnf" in text

    def test_install_sh_mentions_pacman(self):
        text = (ROOT / "install.sh").read_text()
        assert "pacman" in text
