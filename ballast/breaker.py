"""Independent fast drawdown circuit-breaker — the must-not-fail code.

Runs on its own clock (every few minutes), separate from the hourly tick. If
realized drawdown from the running equity peak meets the self-kill threshold, it
flattens the book to the stable asset and pauses the main loop. The threshold is
set well inside the 30% disqualifier; a config that sets it at/over the DQ line is
rejected outright.

Pure decision functions here are unit-tested in isolation; `BreakerClock` is the
thin threading wrapper that drives them in Phase 4.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

DQ_DRAWDOWN = 0.30  # the competition's hard disqualifier; never reach it.


def current_drawdown(equity_curve: Sequence[float]) -> float:
    """Fractional drawdown of the last point from the running peak (0..1)."""
    peak = 0.0
    last = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        last = eq
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - last) / peak)


def breaker_tripped(equity_curve: Sequence[float], threshold: float) -> bool:
    if not 0.0 < threshold < DQ_DRAWDOWN:
        raise ValueError(
            f"breaker threshold must be inside the {DQ_DRAWDOWN:.0%} DQ line, got {threshold}"
        )
    return current_drawdown(equity_curve) >= threshold


class BreakerClock:
    """Drives `breaker_tripped` on its own thread; flattens + pauses on a trip.

    `read_equity_curve` returns the live equity history, `flatten` rotates the
    book to stable, and `pause_event` is set to halt the main tick loop. The
    breaker only ever *adds* safety, so any exception while flattening is logged
    by the caller, never swallowed into a false 'all clear'.
    """

    def __init__(self, read_equity_curve: Callable[[], Sequence[float]],
                 flatten: Callable[[], None], threshold: float,
                 pause_event: threading.Event, interval_s: int = 180) -> None:
        if not 0.0 < threshold < DQ_DRAWDOWN:
            raise ValueError("breaker threshold must be inside the DQ line")
        self._read = read_equity_curve
        self._flatten = flatten
        self._threshold = threshold
        self._pause = pause_event
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check_once(self) -> bool:
        """Single evaluation; trips the breaker if drawdown breached. Returns
        True iff it tripped this call."""
        if self._pause.is_set():
            return False
        if breaker_tripped(self._read(), self._threshold):
            self._flatten()
            self._pause.set()
            return True
        return False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ballast-breaker",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._interval + 1)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.check_once()
