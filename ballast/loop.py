"""The tick orchestrator — one autonomous decision loop on the main clock.

Each tick runs the 6-stage pipeline:
  1 perceive (x402) → 2 regime gate → 3 signal → 4 throttle+size → 5 execute → 6 record

The independent breaker runs on its own clock (own thread) and can flatten +
pause between ticks; the main loop honours the pause flag at the top of each tick.
Journaling is fail-safe: a record failure is swallowed so stages 1–5 always run.
"""

from __future__ import annotations

import logging
import threading
import time

from .breaker import BreakerClock
from .cmc_client import CMCClient, SpendCapError
from .config import Config
from .execute import Executor
from .journal import Journal
from .models import MarketSnapshot, TargetBasket, TickRecord
from .perceive import perceive
from .state import PortfolioState, seed_state
from .strategy import build_target, blended_scores
from .twak_client import TwakClient

log = logging.getLogger("ballast.loop")


class Agent:
    def __init__(self, cfg: Config, universe: list[str], cmc: CMCClient,
                 twak: TwakClient, state: PortfolioState, journal: Journal) -> None:
        self.cfg = cfg
        self.universe = universe
        self.cmc = cmc
        self.state = state
        self.journal = journal
        self.executor = Executor(twak, state, cfg)
        self.pause = threading.Event()
        self.breaker = BreakerClock(
            read_equity_curve=lambda: list(self.state.equity_curve),
            flatten=self._flatten_now,
            threshold=cfg.limits.breaker_drawdown,
            pause_event=self.pause,
            interval_s=cfg.breaker_interval_s,
        )

    # --- one tick ---
    def tick(self, timestamp: float | None = None) -> TickRecord:
        ts = time.time() if timestamp is None else timestamp
        try:
            snapshot = perceive(self.cmc, self.universe, ts)
        except Exception as exc:  # noqa: BLE001 — a data outage must not kill the loop
            log.warning("perceive failed, skipping tick: %s", exc)
            return self._skip_record(ts, f"data unavailable: {exc}")
        self._mark(snapshot)

        if self.pause.is_set():  # breaker fired between ticks
            return self._journal_record(snapshot, TargetBasket({}, 0.0,
                                        regime=None, stable_symbol=self.cfg.stable_symbol),  # type: ignore[arg-type]
                                        [], note="paused by breaker")

        try:
            target = build_target(snapshot, self.cfg)
            trades = self.executor.rebalance(target, self._prices(snapshot))
            signals = self._top_signals(snapshot)
        except SpendCapError as exc:
            log.warning("x402 spend cap hit, holding this tick: %s", exc)
            return self._journal_record(snapshot, TargetBasket({}, 0.0, regime=None,  # type: ignore[arg-type]
                                        stable_symbol=self.cfg.stable_symbol), [],
                                        note=f"spend-cap: {exc}")
        return self._journal_record(snapshot, target, trades, signals=signals)

    # --- run loop ---
    def run(self, max_ticks: int | None = None) -> None:
        self.breaker.start()
        try:
            n = 0
            while max_ticks is None or n < max_ticks:
                self.tick()
                n += 1
                if max_ticks is None or n < max_ticks:
                    time.sleep(self.cfg.tick_interval_s)
        finally:
            self.breaker.stop()

    # --- helpers ---
    def _prices(self, snapshot: MarketSnapshot) -> dict[str, float]:
        return {t.symbol: t.price for t in snapshot.tokens} | {self.cfg.stable_symbol: 1.0}

    def _mark(self, snapshot: MarketSnapshot) -> None:
        self.state.mark_prices(self._prices(snapshot))

    def _flatten_now(self) -> None:
        prices = {s: p.price for s, p in self.state.positions.items()}
        prices[self.cfg.stable_symbol] = 1.0
        self.executor.flatten(prices)

    def _skip_record(self, ts: float, note: str) -> TickRecord:
        """Journal a no-op tick (data outage) without touching positions."""
        rec = TickRecord(
            timestamp=ts, regime="skipped", fear_greed=0, gross_exposure=0.0,
            target_weights={}, trades=[], equity=round(self.state.equity(), 2),
            drawdown=round(self.state.drawdown(), 4), notes=note,
        )
        self.journal.record(rec)
        return rec

    def _top_signals(self, snap: MarketSnapshot, n: int = 6) -> dict[str, float]:
        scores = blended_scores(snap, self.cfg)
        top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:n]
        return {s: round(v, 3) for s, v in top}

    def _journal_record(self, snap: MarketSnapshot, target: TargetBasket,
                        trades: list[dict], note: str = "",
                        signals: dict[str, float] | None = None) -> TickRecord:
        rec = TickRecord(
            timestamp=snap.timestamp,
            regime=target.regime.value if target.regime else "paused",
            fear_greed=snap.fear_greed,
            gross_exposure=target.gross_exposure,
            target_weights={k: round(v, 4) for k, v in target.weights.items()},
            trades=trades,
            equity=round(self.state.equity(), 2),
            drawdown=round(self.state.drawdown(), 4),
            signals=signals or {},
            notes=note,
        )
        self.journal.record(rec)  # fail-safe internally
        return rec


def build_agent(cfg: Config | None = None, start_cash: float = 10_000.0,
                universe: list[str] | None = None, live_data: bool = True) -> Agent:
    """Wire a paper/dry-run agent from config + env. Uses live market data by
    default (free public sources), falling back to the synthetic CMC client if
    those are unreachable. Live *trading* still requires twak and is executor-gated."""
    from .universe import load_universe

    cfg = cfg or Config.from_env()
    uni = universe or load_universe()
    state = seed_state(start_cash)
    journal = Journal()
    data = _build_data_client(cfg, live_data)
    return Agent(cfg, uni, data, TwakClient(mode=cfg.mode), state, journal)


def _build_data_client(cfg: Config, live_data: bool):
    from .cmc_client import from_env as cmc_from_env

    if not live_data:
        return cmc_from_env()
    try:
        from .market_data import MarketDataClient

        return MarketDataClient(quote=cfg.stable_symbol, btc_ma_hours=cfg.btc_ma_hours)
    except Exception as exc:  # noqa: BLE001 — never let data wiring stop startup
        log.warning("live data unavailable (%s); using synthetic CMC client", exc)
        return cmc_from_env()
