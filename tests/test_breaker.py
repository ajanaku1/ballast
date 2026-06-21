"""Independent drawdown circuit-breaker: the must-not-fail code.

Trips when drawdown from the running peak meets/exceeds the threshold. The
threshold is the internal self-kill, set well inside the 30% DQ line.
"""

from __future__ import annotations

import math
import threading

import pytest

from ballast.breaker import current_drawdown, breaker_tripped, BreakerClock


def test_no_drawdown_when_rising():
    assert current_drawdown([100, 110, 120]) == 0.0


def test_drawdown_from_running_peak():
    # peak 120, last 90 -> 25% drawdown
    assert math.isclose(current_drawdown([100, 120, 90]), 0.25, rel_tol=1e-9)


def test_drawdown_uses_peak_not_first():
    assert math.isclose(current_drawdown([100, 80, 120, 60]), 0.5, rel_tol=1e-9)


def test_breaker_trips_at_threshold():
    assert breaker_tripped([100, 85], threshold=0.15) is True   # exactly 15%
    assert breaker_tripped([100, 86], threshold=0.15) is False  # 14%


def test_breaker_safe_on_empty_or_flat():
    assert breaker_tripped([], threshold=0.15) is False
    assert breaker_tripped([100], threshold=0.15) is False


def test_threshold_must_be_inside_dq_line():
    # guardrail: a misconfigured breaker at/over the 30% DQ is rejected.
    with pytest.raises(ValueError):
        breaker_tripped([100, 50], threshold=0.30)


# --- BreakerClock wrapper (decision + side effects, no real timer) ---
def _clock(curve, flatten, pause, threshold=0.15):
    return BreakerClock(lambda: curve, flatten, threshold, pause)


def test_clock_flattens_and_pauses_on_trip():
    flat = {"called": 0}
    pause = threading.Event()
    clock = _clock([100, 80], lambda: flat.__setitem__("called", flat["called"] + 1), pause)
    assert clock.check_once() is True
    assert flat["called"] == 1
    assert pause.is_set()


def test_clock_noop_when_safe():
    flat = {"called": 0}
    pause = threading.Event()
    clock = _clock([100, 95], lambda: flat.__setitem__("called", flat["called"] + 1), pause)
    assert clock.check_once() is False
    assert flat["called"] == 0
    assert not pause.is_set()


def test_clock_does_not_reflatten_while_paused():
    flat = {"called": 0}
    pause = threading.Event()
    pause.set()  # already paused/flattened
    clock = _clock([100, 50], lambda: flat.__setitem__("called", flat["called"] + 1), pause)
    assert clock.check_once() is False
    assert flat["called"] == 0


def test_clock_rejects_threshold_at_dq_line():
    with pytest.raises(ValueError):
        BreakerClock(lambda: [], lambda: None, 0.30, threading.Event())
