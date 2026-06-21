"""One live competition tick — built to be invoked hourly by the scheduler.

Each run is self-contained and reads the chain as source of truth:

  1. sync     — read real USDT (stable) + BNB from the wallet; load tracked
                positions + equity history from state.json.
  2. breaker  — if drawdown from the running peak breached the self-kill, flatten
                to stable and stop (the independent safety, checked each tick).
  3. tick     — perceive real data -> regime -> signal -> size -> execute (gasless
                live swaps via twak) -> journal.
  4. persist  — write state.json (positions + equity curve) for the next run.

Thin-capital tuned (Config.for_thin_capital): tiny min-trade, concentrated basket,
heartbeat trade to keep the >=1-trade/day streak. Gas is sponsored, so the only
per-trade cost is ~0.6% DEX slippage.

  python -m scripts.compete --dry-run   # decide + quote, no broadcast (default)
  python -m scripts.compete --live      # broadcast real gasless swaps
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from ballast.breaker import breaker_tripped
from ballast.config import Config, Mode, Preset
from ballast.loop import Agent
from ballast.journal import Journal
from ballast.market_data import MarketDataClient
from ballast.models import Position
from ballast.state import PortfolioState
from ballast.twak_client import TwakClient
from ballast.universe import load_universe

log = logging.getLogger("ballast.compete")

RPC = "https://bsc-rpc.publicnode.com"
USDT = "0x55d398326f99059fF775485246999027B3197955"
USDC = "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"
STATE = Path("state.json")


def _rpc_balance(addr: str) -> float:
    r = requests.post(RPC, timeout=12, json={"jsonrpc": "2.0", "method": "eth_getBalance",
                      "params": [addr, "latest"], "id": 1})
    return int(r.json()["result"], 16) / 1e18


def _rpc_erc20(token: str, addr: str) -> float:
    data = "0x70a08231000000000000000000000000" + addr[2:]
    r = requests.post(RPC, timeout=12, json={"jsonrpc": "2.0", "method": "eth_call",
                      "params": [{"to": token, "data": data}, "latest"], "id": 1})
    return int(r.json()["result"], 16) / 1e18


def sync_state(agent_addr: str) -> PortfolioState:
    """Seed portfolio state from the chain — the source of truth for the stables
    (USDT cash + USDC held), plus tracked non-stable positions + equity history."""
    usdt = _rpc_erc20(USDT, agent_addr)
    usdc = _rpc_erc20(USDC, agent_addr)
    saved = json.loads(STATE.read_text()) if STATE.exists() else {}
    positions = {
        s: Position(symbol=s, qty=p["qty"], price=p["price"])
        for s, p in saved.get("positions", {}).items() if s != "USDC"
    }
    if usdc > 1e-6:  # USDC is a held stable (from the activity heartbeat)
        positions["USDC"] = Position(symbol="USDC", qty=usdc, price=1.0)
    st = PortfolioState(cash=usdt, positions=positions)
    st.equity_curve = list(saved.get("equity_curve", []))
    st.peak_equity = saved.get("peak_equity", usdt + usdc)
    return st


def persist_state(st: PortfolioState, last_trade_ts: float = 0.0) -> None:
    snap = st.snapshot()
    STATE.write_text(json.dumps({
        "cash": snap["cash"],
        "positions": {s: {"qty": p.qty, "price": p.price} for s, p in st.positions.items()},
        "equity_curve": st.equity_curve[-500:],
        "peak_equity": st.peak_equity,
        "equity": snap["equity"],
        "drawdown": snap["drawdown"],
        "last_trade_ts": last_trade_ts,
    }, indent=2))


def main() -> int:
    load_dotenv(dotenv_path=".env")
    parser = argparse.ArgumentParser(description="Ballast live competition tick")
    parser.add_argument("--live", action="store_true", help="broadcast real swaps")
    parser.add_argument("--dry-run", action="store_true", help="decide + quote only (default)")
    parser.add_argument("--preset", default="conservative")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    import os
    agent_addr = os.environ["BALLAST_AGENT_ADDRESS"]
    mode = Mode.LIVE if args.live else Mode.DRY_RUN
    cfg = Config.for_thin_capital(Preset(args.preset)).replace(mode=mode)

    state = sync_state(agent_addr)
    saved = json.loads(STATE.read_text()) if STATE.exists() else {}
    last_trade_ts = saved.get("last_trade_ts", 0.0)
    now = time.time()
    bnb = _rpc_balance(agent_addr)
    log.info("synced: $%.2f USDT + %.5f BNB + %d positions | mode=%s",
             state.cash, bnb, len(state.positions), mode.value)

    agent = Agent(cfg, load_universe(), MarketDataClient(quote=cfg.stable_symbol,
                  btc_ma_hours=cfg.btc_ma_hours), TwakClient(mode=mode), state, Journal())

    # independent breaker check (each tick — hourly cadence is fine for thin capital)
    if state.equity_curve and breaker_tripped(state.equity_curve, cfg.limits.breaker_drawdown):
        log.warning("BREAKER tripped (dd >= %.0f%%) — flattening to stable",
                    cfg.limits.breaker_drawdown * 100)
        prices = {s: p.price for s, p in state.positions.items()} | {cfg.stable_symbol: 1.0}
        agent.executor.flatten(prices)
        persist_state(state, last_trade_ts)
        return 0

    rec = agent.tick()

    # Activity heartbeat: the competition needs >=1 trade/day. Only when no trade
    # has happened in ~20h AND this tick was flat (e.g. risk-off holding stable),
    # do a tiny USDT->USDC rotation — both are in-scope eligible tokens, so this
    # keeps the day qualified with ~zero slippage and NO price risk (unlike buying
    # a volatile token we'd just sell back next tick).
    needs_activity = (now - last_trade_ts) > 20 * 3600
    if (not rec.trades and needs_activity and cfg.heartbeat_trade_usd > 0
            and state.cash > cfg.heartbeat_trade_usd):
        hb = agent.executor.buy("USDC", cfg.heartbeat_trade_usd, 1.0, "heartbeat (activity)")
        rec.trades.append(hb)
        log.info("  heartbeat USDT->USDC $%.2f tx=%s", cfg.heartbeat_trade_usd, hb.get("tx"))

    if any(t.get("ok") for t in rec.trades):
        last_trade_ts = now
    persist_state(state, last_trade_ts)
    log.info("tick: regime=%s gross=%.0f%% trades=%d equity=$%.2f dd=%.1f%% %s",
             rec.regime, rec.gross_exposure * 100, len(rec.trades), rec.equity,
             rec.drawdown * 100, rec.notes)
    for t in rec.trades:
        log.info("  swap %s->%s $%.2f tx=%s %s", t["sell"], t["buy"], t["usd"],
                 t.get("tx"), t.get("reason", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
