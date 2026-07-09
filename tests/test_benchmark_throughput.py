"""
Lightweight throughput guard for detection-scoring hot path.

This is not a strict microbenchmark. It provides a conservative floor to catch
large accidental regressions in the metric computation path.
"""

import collections
import time
from collections import deque


def test_compute_walk_metrics_throughput_guard(cd):
    now = 1000.0
    key_times = collections.defaultdict(lambda: deque(maxlen=200))

    # Build a realistic active window across many keys.
    for code in range(2, 64):
        key_times[code].extend(
            [
                now - 1.80,
                now - 1.25,
                now - 0.90,
                now - 0.45,
                now - 0.10,
            ]
        )

    iterations = 8000
    start = time.perf_counter()
    for _ in range(iterations):
        _, metrics = cd.compute_walk_metrics(key_times, now)
        assert metrics.unique_keys > 0
    elapsed = time.perf_counter() - start

    ops_per_sec = iterations / max(elapsed, 1e-9)

    # Intentionally conservative to avoid flakiness across CI runners.
    assert ops_per_sec >= 1200, f"Throughput regression suspected: {ops_per_sec:.0f} ops/s"
