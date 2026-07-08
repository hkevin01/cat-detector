"""
Deterministic replay tests for recorded edge traces.
"""

from tests.conftest import EngineHarness


def test_human_trace_stays_below_detection(cd, trace_loader):
    events = trace_loader("human_typing_edge")
    with EngineHarness(cd, sensitivity="high") as h:
        h.replay(events)
        h.flush(0.3)
    assert len(h.detections) == 0


def test_cat_trace_triggers_detection(cd, trace_loader):
    events = trace_loader("cat_walk_burst")
    with EngineHarness(cd, sensitivity="medium") as h:
        h.replay(events)
        h.flush(0.4)
    assert len(h.detections) >= 1
