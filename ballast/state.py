"""Thread-safe portfolio state shared by the two clocks.

The main tick thread and the independent breaker thread both read equity and
drawdown; the breaker may flatten and pause between ticks. All mutation goes
through the lock so the breaker never races a half-applied tick.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .models import Position


@dataclass
class PortfolioState:
    """Holdings + equity history + the drawdown the breaker watches."""

    cash: float = 0.0  # stable-asset balance (USD-equivalent)
    positions: dict[str, Position] = field(default_factory=dict)
    equity_curve: list[float] = field(default_factory=list)
    peak_equity: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # --- reads (cheap, still locked for a consistent snapshot) ---
    def equity(self) -> float:
        with self._lock:
            return self._equity_unlocked()

    def _equity_unlocked(self) -> float:
        return self.cash + sum(p.value for p in self.positions.values())

    def drawdown(self) -> float:
        """Current fractional drawdown from peak equity (0..1)."""
        with self._lock:
            eq = self._equity_unlocked()
            peak = max(self.peak_equity, eq)
            if peak <= 0:
                return 0.0
            return max(0.0, (peak - eq) / peak)

    def weights(self) -> dict[str, float]:
        with self._lock:
            eq = self._equity_unlocked()
            if eq <= 0:
                return {}
            return {s: p.value / eq for s, p in self.positions.items()}

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cash": self.cash,
                "positions": {
                    s: {"qty": p.qty, "price": p.price, "value": p.value}
                    for s, p in self.positions.items()
                },
                "equity": self._equity_unlocked(),
                "peak_equity": self.peak_equity,
                "drawdown": self._drawdown_unlocked(),
            }

    def _drawdown_unlocked(self) -> float:
        eq = self._equity_unlocked()
        peak = max(self.peak_equity, eq)
        return 0.0 if peak <= 0 else max(0.0, (peak - eq) / peak)

    # --- writes ---
    def mark_prices(self, prices: dict[str, float]) -> None:
        """Update position prices, then record equity + peak."""
        with self._lock:
            for sym, pos in self.positions.items():
                if sym in prices:
                    pos.price = prices[sym]
            eq = self._equity_unlocked()
            self.peak_equity = max(self.peak_equity, eq)
            self.equity_curve.append(eq)

    def apply_fill(self, sell: str, buy: str, usd: float, buy_price: float,
                   stable: str) -> None:
        """Apply one executed swap of `usd` from `sell` into `buy`."""
        with self._lock:
            self._debit(sell, usd, stable)
            self._credit(buy, usd, buy_price, stable)

    def _debit(self, sym: str, usd: float, stable: str) -> None:
        if sym == stable:
            self.cash -= usd
            return
        pos = self.positions.get(sym)
        if pos and pos.price > 0:
            pos.qty -= usd / pos.price
            if pos.qty <= 1e-12:
                del self.positions[sym]

    def _credit(self, sym: str, usd: float, price: float, stable: str) -> None:
        if sym == stable:
            self.cash += usd
            return
        pos = self.positions.get(sym)
        if pos:
            pos.qty += usd / price
            pos.price = price
        else:
            self.positions[sym] = Position(symbol=sym, qty=usd / price, price=price)

    # --- persistence (best-effort; state is rebuildable from chain) ---
    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.snapshot(), indent=2))


def seed_state(cash: float) -> PortfolioState:
    """Start flat in the stable asset with a known equity."""
    st = PortfolioState(cash=cash)
    st.peak_equity = cash
    st.equity_curve.append(cash)
    return st
