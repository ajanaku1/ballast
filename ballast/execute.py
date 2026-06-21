"""Stage 5: execution — converge holdings to the target basket via TWAK swaps.

`diff_to_trades` is pure (current weights + target -> swap list) and is shared by
the live loop and the backtest. The `Executor` applies those swaps through the
TWAK client and records the fills in portfolio state. Sells run before buys so
stable is freed before it's spent. A dust threshold suppresses churny micro-swaps.
"""

from __future__ import annotations

import logging

from .config import Config
from .models import TargetBasket, TradeIntent
from .state import PortfolioState
from .twak_client import TwakClient, TwakError, TwakUnavailableError

log = logging.getLogger("ballast.execute")


def diff_to_trades(current: dict[str, float], target: TargetBasket, equity: float,
                   stable: str, min_trade_usd: float = 1.0,
                   stables: frozenset[str] | None = None) -> list[TradeIntent]:
    """Swaps (each routed through the stable asset) to move current -> target.

    `stables` are never rebalanced against each other (so the activity heartbeat's
    USDT<->USDC rotation isn't immediately undone); defaults to just `stable`."""
    held_stable = stables or frozenset({stable})
    symbols = (set(current) | set(target.weights)) - held_stable
    sells: list[TradeIntent] = []
    buys: list[TradeIntent] = []
    for sym in sorted(symbols):
        delta = target.weights.get(sym, 0.0) - current.get(sym, 0.0)
        usd = abs(delta) * equity
        if usd < min_trade_usd:
            continue
        if delta < 0:
            sells.append(TradeIntent(sym, stable, usd, "trim/exit"))
        else:
            buys.append(TradeIntent(stable, sym, usd, "add/enter"))
    return sells + buys


class Executor:
    def __init__(self, twak: TwakClient, state: PortfolioState, cfg: Config) -> None:
        self.twak = twak
        self.state = state
        self.cfg = cfg

    def rebalance(self, target: TargetBasket, prices: dict[str, float]) -> list[dict]:
        equity = self.state.equity()
        trades = diff_to_trades(
            self.state.weights(), target, equity, self.cfg.stable_symbol,
            min_trade_usd=self.cfg.min_trade_usd,
            stables=frozenset(self.cfg.stable_symbols),
        )
        return [self._apply(t, prices) for t in trades]

    def buy(self, symbol: str, usd: float, price: float, reason: str) -> dict:
        """Execute a single explicit buy of `symbol` with stable (used by the
        operator-layer activity heartbeat). Returns the trade record."""
        return self._apply(TradeIntent(self.cfg.stable_symbol, symbol, usd, reason), {symbol: price})

    def flatten(self, prices: dict[str, float]) -> list[dict]:
        """Rotate the entire book to the stable asset (breaker / regime-off)."""
        stable = self.cfg.stable_symbol
        flat = TargetBasket({}, 0.0, regime=None, stable_symbol=stable)  # type: ignore[arg-type]
        return self.rebalance(flat, prices)

    def _apply(self, t: TradeIntent, prices: dict[str, float]) -> dict:
        buy_price = prices.get(t.buy_symbol, 1.0)
        try:
            res = self.twak.swap(t.sell_symbol, t.buy_symbol, t.usd_amount, buy_price, t.reason)
        except (TwakError, TwakUnavailableError) as exc:
            # A transient swap failure must not abort the tick or corrupt state —
            # log it, leave holdings untouched, retry on the next tick.
            log.warning("swap %s->%s $%.2f failed: %s", t.sell_symbol, t.buy_symbol,
                        t.usd_amount, exc)
            return {"sell": t.sell_symbol, "buy": t.buy_symbol,
                    "usd": round(t.usd_amount, 2), "tx": None, "ok": False,
                    "reason": t.reason, "note": f"failed: {exc}"}
        if res.ok:
            self.state.apply_fill(
                t.sell_symbol, t.buy_symbol, t.usd_amount, res.fill_price,
                self.cfg.stable_symbol,
            )
        return {
            "sell": t.sell_symbol,
            "buy": t.buy_symbol,
            "usd": round(t.usd_amount, 2),
            "tx": res.tx_hash,
            "ok": res.ok,
            "reason": t.reason,
            "note": res.note,
        }
