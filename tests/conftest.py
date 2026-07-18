"""
conftest.py — shared pytest fixtures and helpers for cat-detector tests.

All fixtures that require evdev or pynput mock the import so the test suite
runs on any platform (Linux, Windows, macOS) without hardware access.
"""
import json
import queue
import sys
import time
import types
from pathlib import Path
import unittest.mock as mock

import pytest


# ---------------------------------------------------------------------------
# Minimal evdev stub so cat_detector imports cleanly on non-Linux hosts
# ---------------------------------------------------------------------------

def _make_evdev_stub():
    evdev_mod = types.ModuleType("evdev")

    class _Ecodes:
        EV_KEY = 1

    class _InputDevice:
        def __init__(self, path):
            self.name = "Fake Keyboard"
            self.path = path
        def capabilities(self):
            return {1: list(range(30))}

    evdev_mod.ecodes        = _Ecodes()
    evdev_mod.InputDevice   = _InputDevice
    evdev_mod.list_devices  = lambda: []
    evdev_mod.categorize    = lambda e: e
    return evdev_mod


@pytest.fixture(scope="session", autouse=True)
def patch_platform_imports():
    """Install lightweight stubs for evdev / pynput / winotify."""
    sys.modules.setdefault("evdev", _make_evdev_stub())

    pynput = types.ModuleType("pynput")
    kb     = types.ModuleType("pynput.keyboard")
    kb.Listener = mock.MagicMock()
    pynput.keyboard = kb
    sys.modules.setdefault("pynput",           pynput)
    sys.modules.setdefault("pynput.keyboard",  kb)

    winotify = types.ModuleType("winotify")
    winotify.Notification = mock.MagicMock()
    sys.modules.setdefault("winotify", winotify)
    yield


@pytest.fixture(scope="session")
def cd():
    """Import and return the cat_detector module once per session."""
    if "cat_detector" in sys.modules:
        return sys.modules["cat_detector"]
    with mock.patch("platform.system", return_value="Linux"):
        import cat_detector
    return cat_detector


@pytest.fixture(autouse=True)
def reset_runtime_safety_state(cd):
    """Keep lock/action safety state deterministic across tests."""
    cd.reset_lock_circuit_state()
    if hasattr(cd, "reset_action_safety_state"):
        cd.reset_action_safety_state(now=0.0)
    yield


# ---------------------------------------------------------------------------
# Engine harness
# ---------------------------------------------------------------------------

class _FakeArgs:
    def __init__(self, sensitivity="medium", toddler=False,
                 lock=False, sound=False, pause_secs=0, lock_profile=None, **extra):
        self.sensitivity = sensitivity
        self.toddler     = toddler
        self.lock        = lock
        self.sound       = sound
        self.pause_secs  = pause_secs
        self.lock_profile = lock_profile
        for key, value in extra.items():
            setattr(self, key, value)


class EngineHarness:
    """
    Drives _detection_engine via a SimpleQueue and records detections.

    Usage::

        with EngineHarness(cd, sensitivity="high") as h:
            for code in cat_walk_codes:
                h.key_down(code)
            h.flush()
            assert len(h.detections) == 1
    """

    def __init__(self, cd_module, **args_kw):
        self._cd   = cd_module
        self._eq   = queue.SimpleQueue()
        self._args = _FakeArgs(**args_kw)
        self.detections: list[str] = []
        self.records = []

    def __enter__(self):
        import threading
        self._p_notify = mock.patch.object(
            self._cd, "notify",
            side_effect=lambda msg, urgency="critical": self.detections.append(msg),
        )
        self._p_lock  = mock.patch.object(self._cd, "lock_screen")
        self._p_sound = mock.patch.object(self._cd, "play_meow")
        self._p_record = mock.patch.object(
            self._cd,
            "record_detection_event",
            side_effect=lambda rec: self.records.append(rec),
        )
        self._p_notify.start()
        self._p_lock.start()
        self._p_sound.start()
        self._p_record.start()
        self._thread = threading.Thread(
            target=self._cd._detection_engine,
            args=(self._eq, self._args),
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._p_notify.stop()
        self._p_lock.stop()
        self._p_sound.stop()
        self._p_record.stop()

    def key_down(self, code: int):
        self._eq.put(("down", code))

    def key_up(self, code: int):
        self._eq.put(("up", code))

    def key_hold(self, code: int):
        self._eq.put(("hold", code))

    def flush(self, secs: float = 0.25):
        time.sleep(secs)

    def replay(self, events, speed: float = 1.0):
        """Replay a deterministic event trace into the engine."""
        for ev in events:
            kind = ev["kind"]
            code = int(ev["code"])
            delay = float(ev.get("delay", 0.0))
            self._eq.put((kind, code))
            if delay > 0:
                time.sleep(delay / max(speed, 0.001))


@pytest.fixture
def engine_factory(cd):
    """Return a callable that builds an EngineHarness with given kwargs."""
    def _make(**kw):
        return EngineHarness(cd, **kw)
    return _make


@pytest.fixture
def trace_loader():
    """Load replay traces from tests/fixtures/traces/*.json."""
    base = Path(__file__).parent / "fixtures" / "traces"

    def _load(name: str):
        with (base / f"{name}.json").open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
        return payload["events"]

    return _load
