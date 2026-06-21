"""Shared, typed data contracts passed between pipeline stages.

Plain dataclasses, no behaviour — every stage consumes and produces these so the
boundaries stay clean and each stage is independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Regime(str, Enum):
    """Output of the BTC moving-average regime gate."""

    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"


@dataclass(frozen=True)
class TokenSnapshot:
    """One token's perceived state for a single tick.

    Derivatives fields (funding_rate, open_interest, oi_change_24h) are *signals*
    only — Ballast never takes a derivatives position. They may be None when CMC
    has no derivatives coverage for a token; signals must degrade gracefully.
    """

    symbol: str
    address: str
    price: float
    return_24h: float  # fractional, e.g. 0.05 == +5%
    realized_vol: float  # annualised or per-window stdev of returns, > 0
    funding_rate: float | None = None  # fractional per funding interval
    open_interest: float | None = None  # USD notional
    oi_change_24h: float | None = None  # fractional change in OI


@dataclass(frozen=True)
class MarketSnapshot:
    """Everything perceived in stage 1, consumed by the rest of the tick."""

    timestamp: float
    btc_price: float
    btc_ma: float  # ~150-hour moving average used by the regime gate
    fear_greed: int  # 0..100 CMC Fear & Greed index
    tokens: tuple[TokenSnapshot, ...]


@dataclass(frozen=True)
class TargetBasket:
    """Output of signal + risk: desired portfolio for this tick.

    weights are fractions of total equity that sum to gross_exposure (<= 1.0);
    the remainder is held in the stable asset. regime is carried for journaling.
    """

    weights: dict[str, float]
    gross_exposure: float
    regime: Regime
    stable_symbol: str = "USDT"


@dataclass
class Position:
    """A currently-held spot position."""

    symbol: str
    qty: float
    price: float

    @property
    def value(self) -> float:
        return self.qty * self.price


@dataclass
class TradeIntent:
    """A single swap the executor should perform to converge to target."""

    sell_symbol: str
    buy_symbol: str
    usd_amount: float
    reason: str = ""


@dataclass
class TickRecord:
    """The decision journal entry for one tick (stage 6, fail-safe)."""

    timestamp: float
    regime: str
    fear_greed: int
    gross_exposure: float
    target_weights: dict[str, float]
    trades: list[dict] = field(default_factory=list)
    equity: float = 0.0
    drawdown: float = 0.0
    signals: dict[str, float] = field(default_factory=dict)  # top blended z-scores (rationale)
    notes: str = ""
