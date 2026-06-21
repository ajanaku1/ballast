"""Backtest gate: prove the strategy + risk overlay hold max drawdown under the
30% disqualifier *before* any live wiring.

The harness is data-source agnostic: it runs over a list of `MarketSnapshot`,
which can come from real CMC history (CSV loader, TODO) or the bundled synthetic
generator. It drives the *same* `build_target` + `Executor` + breaker the live
agent uses, so what passes here is what trades live.

Run:  python -m backtest.backtest
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ballast.breaker import breaker_tripped
from ballast.config import Config, Preset
from ballast.execute import Executor
from ballast.models import MarketSnapshot, TokenSnapshot
from ballast.state import seed_state
from ballast.strategy import build_target
from ballast.twak_client import TwakClient


@dataclass
class BacktestResult:
    preset: str
    equity_curve: list[float]
    total_return: float
    max_drawdown: float
    sharpe: float
    n_trades: int
    breaker_fired: bool

    def passes_gate(self, cap: float = 0.30, margin: float = 0.05) -> bool:
        return self.max_drawdown < (cap - margin)


def max_drawdown(curve: list[float]) -> float:
    peak, mdd = 0.0, 0.0
    for eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            mdd = max(mdd, (peak - eq) / peak)
    return mdd


def sharpe(curve: list[float]) -> float:
    rets = [curve[i] / curve[i - 1] - 1 for i in range(1, len(curve)) if curve[i - 1] > 0]
    if len(rets) < 2:
        return 0.0
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    return 0.0 if sd == 0 else (mu / sd) * math.sqrt(len(rets))


def run(snapshots: list[MarketSnapshot], cfg: Config,
        start_cash: float = 10_000.0) -> BacktestResult:
    state = seed_state(start_cash)
    executor = Executor(TwakClient(mode=cfg.mode), state, cfg)
    stable = cfg.stable_symbol
    threshold = cfg.limits.breaker_drawdown
    n_trades, paused, fired = 0, False, False

    for snap in snapshots:
        prices = {t.symbol: t.price for t in snap.tokens} | {stable: 1.0}
        state.mark_prices(prices)
        if not paused and breaker_tripped(state.equity_curve, threshold):
            executor.flatten(prices)
            paused, fired = True, True
            continue
        if paused:
            continue
        target = build_target(snap, cfg)
        n_trades += len(executor.rebalance(target, prices))

    curve = state.equity_curve
    return BacktestResult(
        preset=cfg.preset.value,
        equity_curve=curve,
        total_return=curve[-1] / curve[0] - 1 if curve and curve[0] > 0 else 0.0,
        max_drawdown=max_drawdown(curve),
        sharpe=sharpe(curve),
        n_trades=n_trades,
        breaker_fired=fired,
    )


# --- synthetic data (stand-in for CMC history; real CSV loader plugs in here) ---
def synthetic_panel(n_assets: int = 20, n_steps: int = 400, seed: int = 7,
                    crash_at: int | None = 250) -> list[MarketSnapshot]:
    """Correlated random-walk universe with a market-wide crash + a funding/OI
    cascade signal that *leads* the crash, so a working funding-shadow exits in
    time. Deterministic given the seed."""
    rng = random.Random(seed)
    syms = [f"TKN{i:02d}" for i in range(n_assets)]
    prices = {s: rng.uniform(0.5, 50.0) for s in syms}
    vols = {s: rng.uniform(0.4, 1.2) for s in syms}
    btc = 60_000.0
    btc_hist: list[float] = []
    snaps: list[MarketSnapshot] = []

    for t in range(n_steps):
        crashing = crash_at is not None and crash_at <= t < crash_at + 30
        btc_drift = -0.02 if crashing else 0.0008
        btc *= 1 + btc_drift + rng.gauss(0, 0.01)
        btc_hist.append(btc)
        btc_ma = sum(btc_hist[-150:]) / len(btc_hist[-150:])
        fng = 80 if (crash_at and crash_at - 20 <= t < crash_at) else rng.randint(20, 60)

        tokens = []
        for s in syms:
            mkt = -0.05 if crashing else 0.001
            ret = mkt + rng.gauss(0, vols[s] * 0.06)
            prices[s] = max(1e-4, prices[s] * (1 + ret))
            # Funding turns hot (crowded longs) just before the crash -> bearish.
            pre = crash_at is not None and crash_at - 15 <= t < crash_at
            funding = rng.uniform(0.0006, 0.0015) if pre else rng.gauss(0, 0.0004)
            tokens.append(TokenSnapshot(
                symbol=s, address="0x0", price=prices[s], return_24h=ret,
                realized_vol=vols[s], funding_rate=funding,
                open_interest=rng.uniform(1e6, 1e8),
                oi_change_24h=rng.uniform(0.1, 0.5) if pre else rng.gauss(0, 0.1),
            ))
        snaps.append(MarketSnapshot(float(t), btc, btc_ma, fng, tuple(tokens)))
    return snaps


def _report(r: BacktestResult) -> str:
    gate = "PASS" if r.passes_gate() else "FAIL"
    return (
        f"[{r.preset:>12}] return {r.total_return:+7.1%}  maxDD {r.max_drawdown:6.1%}  "
        f"Sharpe {r.sharpe:5.2f}  trades {r.n_trades:4d}  "
        f"breaker {'fired' if r.breaker_fired else 'idle '}  gate {gate}"
    )


def main() -> int:
    snaps = synthetic_panel()
    ok = True
    print("Ballast backtest gate — max DD must hold < 25% (30% DQ less 5% margin)\n")
    for preset in (Preset.CONSERVATIVE, Preset.AGGRESSIVE):
        r = run(snaps, Config.from_preset(preset))
        print(_report(r))
        ok = ok and r.passes_gate()
    print("\nGATE:", "PASS — clear to wire live (after checkpoints)" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
