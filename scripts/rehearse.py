"""Testnet / dry-run rehearsal of the full live loop — spends nothing.

Proves the complete pipeline on real market data without broadcasting any trade:

  1. live data        — real funding/price/vol/F&G over the competition universe
  2. one real tick     — perceive -> regime -> signal -> size -> (dry-run) -> journal
  3. execution path    — top real signals -> live twak routing quotes (not broadcast)
  4. on-chain readiness — what's already done vs. what still needs funds

Run:  python -m scripts.rehearse
"""

from __future__ import annotations

import json
from dataclasses import replace

import requests
from dotenv import load_dotenv

from ballast.config import Config, Mode, Preset
from ballast.execute import Executor
from ballast.market_data import MarketDataClient
from ballast.models import TargetBasket
from ballast.state import seed_state
from ballast.strategy import build_target, blended_scores
from ballast.twak_client import TwakClient

AGENT = "0x05e690aE1a0D9865f3d71E28c3e50d56A1ecbd94"
RPC = {"mainnet": "https://bsc-rpc.publicnode.com",
       "testnet": "https://bsc-testnet-rpc.publicnode.com"}


def _bnb(rpc: str) -> float:
    try:
        r = requests.post(rpc, json={"jsonrpc": "2.0", "method": "eth_getBalance",
                                     "params": [AGENT, "latest"], "id": 1}, timeout=10)
        return int(r.json()["result"], 16) / 1e18
    except Exception:  # noqa: BLE001
        return -1.0


def _hr(title: str) -> None:
    print(f"\n{'─' * 64}\n  {title}\n{'─' * 64}")


def main() -> int:
    load_dotenv(dotenv_path=".env")
    cfg = Config.from_preset(Preset.CONSERVATIVE).replace(mode=Mode.DRY_RUN)
    data = MarketDataClient(quote=cfg.stable_symbol, btc_ma_hours=cfg.btc_ma_hours)

    _hr("1 · LIVE DATA (real, free sources — no spend)")
    snap = data.fetch_snapshot(_universe(), 0.0)
    regime = "RISK-ON" if snap.btc_price > snap.btc_ma else "RISK-OFF"
    print(f"  universe priced: {len(snap.tokens)} tokens | F&G {snap.fear_greed}")
    print(f"  BTC ${snap.btc_price:,.0f} vs 150h MA ${snap.btc_ma:,.0f} -> {regime}")

    _hr("2 · ONE REAL TICK (honours the live regime)")
    target = build_target(snap, cfg)
    print(f"  regime gate -> gross {target.gross_exposure:.0%}, "
          f"basket {list(target.weights) or '(stable — risk-off)'}")
    scores = blended_scores(snap, cfg)
    top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:6]
    print(f"  top signals: " + ", ".join(f"{s} {v:+.2f}" for s, v in top))

    _hr("3 · EXECUTION PATH (top real signals -> live twak quotes, NOT broadcast)")
    _rehearse_execution(cfg, snap, [s for s, _ in top])

    _hr("4 · ON-CHAIN READINESS")
    _readiness()
    return 0


def _rehearse_execution(cfg: Config, snap, symbols: list[str]) -> None:
    twak = TwakClient(mode=Mode.DRY_RUN)
    tradeable = [s for s in symbols if twak.resolve_token(s)][:3]
    if not tradeable:
        print("  no top-signal token resolved on BSC this tick")
        return
    weight = round(min(cfg.limits.max_token_weight, 1.0 / len(tradeable)), 4)
    basket = TargetBasket({s: weight for s in tradeable}, weight * len(tradeable),
                          regime=None, stable_symbol=cfg.stable_symbol)  # type: ignore[arg-type]
    state = seed_state(1000.0)
    prices = {t.symbol: t.price for t in snap.tokens} | {cfg.stable_symbol: 1.0}
    for r in Executor(twak, state, cfg).rebalance(basket, prices):
        print(f"  {r['sell']} -> {r['buy']:6} ${r['usd']:>7.2f}   {r['note']}")


def _readiness() -> None:
    main_bnb, test_bnb = _bnb(RPC["mainnet"]), _bnb(RPC["testnet"])
    rows = [
        ("Competition registration (mainnet)", "DONE", "tx 0xaf91…9554"),
        ("Agent wallet (shared twak+bnbagent)", "DONE", AGENT),
        ("Live data + signal + risk overlay", "DONE", "real, this run"),
        ("Execution routing (dry-run quotes)", "DONE", "real twak routing"),
        ("Mainnet BNB (gas / trading capital)", f"${main_bnb*600:.2f}",
         f"{main_bnb:.5f} BNB — gasless swaps make this go far"),
        ("Testnet tBNB (for ERC-8004 rehearsal)", "NEEDED" if test_bnb <= 0 else "OK",
         "faucet: https://www.bnbchain.org/en/testnet-faucet"),
        ("USDC (for x402 paid CMC data)", "OPTIONAL", "free Binance/alt.me used instead"),
    ]
    for name, status, note in rows:
        print(f"  [{status:^7}] {name:<38} {note}")


def _universe() -> list[str]:
    from ballast.universe import load_universe
    return load_universe()


if __name__ == "__main__":
    raise SystemExit(main())
