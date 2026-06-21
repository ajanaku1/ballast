"""Stage 2: BTC moving-average regime gate.

A single market-wide kill-switch. If BTC trades at or below its ~150-hour moving
average, the macro tape is hostile to a long-only basket — rotate everything to
the stable asset and skip signal/sizing for this tick. Survival-biased: exactly
at the MA counts as risk-off (no demonstrated edge to be long).
"""

from __future__ import annotations

from .models import MarketSnapshot, Regime


def evaluate(snapshot: MarketSnapshot) -> Regime:
    return Regime.RISK_ON if snapshot.btc_price > snapshot.btc_ma else Regime.RISK_OFF
