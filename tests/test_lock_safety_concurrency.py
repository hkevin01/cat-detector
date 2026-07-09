"""
Concurrency stress tests for lock safety circuit behavior.
"""

import threading


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
