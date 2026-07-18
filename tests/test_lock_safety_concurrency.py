"""
Concurrency stress tests for lock safety circuit behavior.
"""

import threading
import time
from types import SimpleNamespace


def test_lock_circuit_allows_only_one_lock_in_same_window(cd):
    cd.reset_lock_circuit_state()
    results = []
    guard = threading.Lock()

    def worker():
        allowed = cd.lock_circuit_allows(now=1000.0)
        with guard:
            results.append(allowed)

    threads = [threading.Thread(target=worker) for _ in range(64)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(1 for x in results if x) == 1


def test_lock_circuit_concurrency_respects_session_cap(cd):
    cd.reset_lock_circuit_state()
    interval = cd.LOCK_CIRCUIT_MIN_INTERVAL_SECS
    now_points = [
        1000.0,
        1000.0 + interval + 1.0,
        1000.0 + (2 * interval) + 2.0,
        1000.0 + (3 * interval) + 3.0,
    ]

    results = []
    guard = threading.Lock()

    def worker(now_value: float):
        allowed = cd.lock_circuit_allows(now=now_value)
        with guard:
            results.append(allowed)

    threads = [threading.Thread(target=worker, args=(n,)) for n in now_points for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(1 for x in results if x) == cd.LOCK_CIRCUIT_MAX_PER_SESSION


def test_dispatch_throttle_blocks_action_storms(cd):
    args = SimpleNamespace(sound=False, lock=False)
    called = {"notify": 0}

    old_notify = cd.notify
    old_neutralize = cd.neutralize_active_input
    try:
        cd.notify = lambda *_a, **_kw: called.__setitem__("notify", called["notify"] + 1)
        cd.neutralize_active_input = lambda *_a, **_kw: None

        cd.dispatch_detection_actions(args, "cat", "walking", now_monotonic=1000.0)
        cd.dispatch_detection_actions(args, "cat", "walking", now_monotonic=1000.1)
    finally:
        cd.notify = old_notify
        cd.neutralize_active_input = old_neutralize

    assert called["notify"] == 1


def test_dispatch_busy_guard_prevents_reentrant_actions(cd):
    args = SimpleNamespace(sound=False, lock=False)
    called = {"notify": 0}

    old_notify = cd.notify
    old_neutralize = cd.neutralize_active_input
    try:
        def _slow_notify(*_a, **_kw):
            called["notify"] += 1
            time.sleep(0.2)

        cd.notify = _slow_notify
        cd.neutralize_active_input = lambda *_a, **_kw: None

        results = []
        guard = threading.Lock()

        def worker(idx: int):
            outcome = cd.dispatch_detection_actions(
                args,
                "cat",
                "walking",
                now_monotonic=1000.0 + (idx * 0.01),
            )
            with guard:
                results.append(outcome)

        t1 = threading.Thread(target=worker, args=(0,))
        t2 = threading.Thread(target=worker, args=(1,))
        t1.start()
        time.sleep(0.02)
        t2.start()
        t1.join()
        t2.join()
    finally:
        cd.notify = old_notify
        cd.neutralize_active_input = old_neutralize

    assert called["notify"] == 1
    assert results.count("neutralized-only") == 2


def test_lock_timeout_prevents_hanging_action(cd):
    args = SimpleNamespace(sound=False, lock=True, lock_profile="all")
    old_notify = cd.notify
    old_neutralize = cd.neutralize_active_input
    old_lock = cd.lock_screen
    old_should_lock = cd.should_lock_for_reason
    old_lock_circuit_allows = cd.lock_circuit_allows
    try:
        cd.notify = lambda *_a, **_kw: None
        cd.neutralize_active_input = lambda *_a, **_kw: None
        cd.should_lock_for_reason = lambda *_a, **_kw: True
        cd.lock_circuit_allows = lambda *_a, **_kw: True

        def _slow_lock(*_a, **_kw):
            time.sleep(cd.ACTION_LOCK_TIMEOUT_SECS + 0.2)

        cd.lock_screen = _slow_lock
        start = time.monotonic()
        outcome = cd.dispatch_detection_actions(
            args,
            "cat",
            "walking",
            now_monotonic=2000.0,
        )
        elapsed = time.monotonic() - start
    finally:
        cd.notify = old_notify
        cd.neutralize_active_input = old_neutralize
        cd.lock_screen = old_lock
        cd.should_lock_for_reason = old_should_lock
        cd.lock_circuit_allows = old_lock_circuit_allows

    assert outcome == "neutralized-only"
    assert elapsed < (cd.ACTION_LOCK_TIMEOUT_SECS + 0.6)


def test_failure_circuit_temporarily_disables_lock(cd):
    args = SimpleNamespace(sound=False, lock=True, lock_profile="all")
    called = {"lock": 0}
    old_notify = cd.notify
    old_neutralize = cd.neutralize_active_input
    old_lock = cd.lock_screen
    old_should_lock = cd.should_lock_for_reason
    old_lock_circuit_allows = cd.lock_circuit_allows
    try:
        cd.notify = lambda *_a, **_kw: None
        cd.neutralize_active_input = lambda *_a, **_kw: None
        cd.should_lock_for_reason = lambda *_a, **_kw: True
        cd.lock_circuit_allows = lambda *_a, **_kw: True

        def _fail_lock(*_a, **_kw):
            called["lock"] += 1
            raise RuntimeError("lock failed")

        cd.lock_screen = _fail_lock
        base = 3000.0
        step = cd.LOCK_CIRCUIT_MIN_INTERVAL_SECS + 1.0
        for i in range(cd.ACTION_FAILURE_MAX_CONSECUTIVE + 2):
            cd.dispatch_detection_actions(
                args,
                "cat",
                "walking",
                now_monotonic=base + (i * step),
            )
        before = called["lock"]
        cd.dispatch_detection_actions(
            args,
            "cat",
            "walking",
            now_monotonic=base + ((cd.ACTION_FAILURE_MAX_CONSECUTIVE + 1) * step) + 10.0,
        )
    finally:
        cd.notify = old_notify
        cd.neutralize_active_input = old_neutralize
        cd.lock_screen = old_lock
        cd.should_lock_for_reason = old_should_lock
        cd.lock_circuit_allows = old_lock_circuit_allows

    assert before >= 1
    assert called["lock"] == before


def test_startup_grace_blocks_initial_locks(cd):
    args = SimpleNamespace(sound=False, lock=True, lock_profile="all")
    called = {"lock": 0}
    old_notify = cd.notify
    old_neutralize = cd.neutralize_active_input
    old_lock = cd.lock_screen
    old_should_lock = cd.should_lock_for_reason
    try:
        cd.notify = lambda *_a, **_kw: None
        cd.neutralize_active_input = lambda *_a, **_kw: None
        cd.should_lock_for_reason = lambda *_a, **_kw: True
        cd.lock_screen = lambda *_a, **_kw: called.__setitem__("lock", called["lock"] + 1)

        cd.reset_action_safety_state(now=1000.0)
        cd.dispatch_detection_actions(args, "cat", "walking", now_monotonic=1002.0)
        cd.dispatch_detection_actions(
            args,
            "cat",
            "walking",
            now_monotonic=1000.0 + cd.ACTION_LOCK_STARTUP_GRACE_SECS + 2.0,
        )
    finally:
        cd.notify = old_notify
        cd.neutralize_active_input = old_neutralize
        cd.lock_screen = old_lock
        cd.should_lock_for_reason = old_should_lock

    assert called["lock"] == 1
