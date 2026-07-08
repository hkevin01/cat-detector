"""
Platform abstraction tests.

These tests verify platform-specific code paths (notify, lock_screen,
play_meow) without actually calling OS APIs.  Both Linux and Windows
branches are exercised via mocking.
"""
import sys
import unittest.mock as mock


class TestNotifyLinux:
    def test_notify_calls_notify_send_when_available(self, cd):
        with mock.patch.object(cd, "_PLATFORM", "Linux"),                  mock.patch("shutil.which", return_value="/usr/bin/notify-send"),                  mock.patch("subprocess.run") as mock_run:
            cd.notify("test message")
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "notify-send" in args

    def test_notify_falls_back_to_console_without_notify_send(self, cd, capsys):
        with mock.patch.object(cd, "_PLATFORM", "Linux"),                  mock.patch("shutil.which", return_value=None):
            cd.notify("console fallback test")
        captured = capsys.readouterr()
        assert "console fallback test" in captured.out

    def test_notify_prints_message_always(self, cd, capsys):
        with mock.patch.object(cd, "_PLATFORM", "Linux"),                  mock.patch("shutil.which", return_value=None):
            cd.notify("always printed")
        assert "always printed" in capsys.readouterr().out


class TestNotifyWindows:
    def test_notify_windows_calls_winotify(self, cd):
        fake_notif = mock.MagicMock()
        fake_cls   = mock.MagicMock(return_value=fake_notif)
        fake_mod   = mock.MagicMock()
        fake_mod.Notification = fake_cls

        with mock.patch.object(cd, "_PLATFORM", "Windows"),                  mock.patch.dict(sys.modules, {"winotify": fake_mod}):
            cd.notify("windows test")
        fake_cls.assert_called_once()
        fake_notif.show.assert_called_once()


class TestLockScreenLinux:
    def test_lock_calls_loginctl_when_present(self, cd):
        with mock.patch.object(cd, "_PLATFORM", "Linux"),                  mock.patch("shutil.which", return_value="/bin/loginctl"),                  mock.patch("subprocess.run") as mock_run:
            cd.lock_screen()
        mock_run.assert_called_once()
        assert "loginctl" in mock_run.call_args[0][0]

    def test_lock_falls_back_to_xdg(self, cd):
        def _which(cmd):
            return "/usr/bin/xdg-screensaver" if cmd == "xdg-screensaver" else None
        with mock.patch.object(cd, "_PLATFORM", "Linux"),                  mock.patch("shutil.which", side_effect=_which),                  mock.patch("subprocess.run") as mock_run:
            cd.lock_screen()
        mock_run.assert_called_once()
        assert "xdg-screensaver" in mock_run.call_args[0][0]

    def test_lock_logs_warning_when_no_locker_found(self, cd, caplog):
        with mock.patch.object(cd, "_PLATFORM", "Linux"),                  mock.patch("shutil.which", return_value=None):
            import logging
            with caplog.at_level(logging.WARNING, logger="cat-detector"):
                cd.lock_screen()
        assert any("lock" in r.message.lower() for r in caplog.records)


class TestLockScreenWindows:
    def test_lock_calls_lockworkstation(self, cd):
        fake_user32 = mock.MagicMock()
        with mock.patch.object(cd, "_PLATFORM", "Windows"),                  mock.patch.object(cd, "_user32", fake_user32, create=True):
            cd.lock_screen()
        fake_user32.LockWorkStation.assert_called_once()


class TestPlayMeow:
    def test_no_crash_when_asset_missing(self, cd):
        with mock.patch("os.path.exists", return_value=False):
            cd.play_meow()   # must not raise

    def test_linux_tries_paplay_first(self, cd):
        with mock.patch.object(cd, "_PLATFORM", "Linux"),                  mock.patch("os.path.exists", return_value=True),                  mock.patch("shutil.which", return_value="/usr/bin/paplay"),                  mock.patch("subprocess.Popen") as mock_popen:
            cd.play_meow()
        mock_popen.assert_called_once()
        assert "paplay" in mock_popen.call_args[0][0][0]
