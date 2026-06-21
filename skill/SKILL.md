---
name: funding-shadow-spot
title: Funding-Shadow Spot Rotation
version: 1.0.0
author: Ballast
category: trading-strategy
chain: bsc
instruments: spot
description: >
  Cross-sectional spot rotation that reads where leverage is about to break.
  Uses CoinMarketCap derivatives data (funding rate + open interest) as a *signal*
  for spot positioning, never holding a derivatives position, and wraps every
  decision in a survival-first risk overlay tuned to hold max drawdown under a
  30% hard cap. Built for the spot-only Trust Wallet Agent Kit.
inputs:
  - cmc:derivatives/funding-rate      # per-token funding, the crowding gauge
  - cmc:derivatives/open-interest     # leverage stacked; conviction amplifier
  - cmc:fear-and-greed                # gross-exposure throttle
  - cmc:quotes/price-vol              # price, 24h return, realized vol
  - cmc:quotes/btc                    # regime gate input (price vs 150h MA)
outputs:
  - target_basket                     # {symbol: weight} long-only spot basket
  - gross_exposure                    # 0.40–1.00, F&G-driven
  - regime                            # risk_on | risk_off
universe: bep20-149                   # competition fixed list; trades outside don't count
cadence: hourly
---

# Funding-Shadow Spot Rotation

## Thesis
Crowded leverage unwinds violently. When perpetual **funding is deeply negative**,
shorts are crowded and paying to stay short, that is *short-squeeze fuel*, bullish
for a spot long entered **before** the cascade. Deeply **positive funding** means
crowded longs and long-squeeze (downside) risk, bearish. **Rising open interest**
means more leverage stacked, so the eventual unwind is larger; it amplifies
conviction in either direction. We harvest this with **spot only**, derivatives
data is the map, never the position.

## Workflow (one decision per tick)
1. **Perceive (pay-per-query).** Buy only this tick's data via x402: funding + OI
   for the universe, Fear & Greed, price/return/vol, and BTC for the regime gate.
2. **Regime gate.** If BTC ≤ its ~150-hour moving average, rotate the whole book
   to a stablecoin and stop. No edge being long a falling market.
3. **Signal.** For each token compute `funding_shadow = z(-funding × (1 + max(0, ΔOI)))`
   and `momentum = z(return_24h)`. Blend: `score = w·funding_shadow + (1-w)·momentum`
   (`w` default 0.5). Select the top *N* (8 conservative / 12 aggressive) with
   **positive** score, long-only, no dead weight.
4. **Throttle + size.** Fear & Greed sets gross exposure contrarian: fear opens to
   the max, greed reefs toward the min (40–100% band). Within that gross, size by
   **inverse volatility**, cap any single token at 20–30%, and redistribute the
   capped excess to uncapped names. Undeployable weight stays in stable.
5. **Execute.** Diff target vs current; swap only the deltas on BSC (spot, self-custody),
   sells before buys, suppressing dust.
6. **Record.** Write the decision + rationale (regime, F&G, top scores, trades) to a
   tamper-evident journal under the agent's on-chain identity.

## Risk overlay (the product)
- **Per-token cap** (20–30%) so no single name can breach the drawdown budget.
- **Inverse-vol sizing** so calmer names carry more of the book.
- **F&G throttle** cuts gross into euphoria, the regime that breaks momentum bots.
- **BTC regime kill-switch** flattens to stable in hostile macro.
- **Independent drawdown circuit-breaker** on its own clock (every few minutes)
  flattens + pauses at the internal self-kill (15% conservative / 25% aggressive),
  well inside the 30% disqualifier.

## Output template
```json
{
  "timestamp": 1781910172.7,
  "regime": "risk_on",
  "fear_greed": 28,
  "gross_exposure": 0.76,
  "target_weights": {"BNB": 0.20, "INJ": 0.154, "CAKE": 0.128, "...": 0.0},
  "signals": {"INJ": 1.84, "BNB": 1.52, "AAVE": 1.19},
  "trades": [{"sell": "USDT", "buy": "INJ", "usd": 612.0, "tx": "0x4af9…"}],
  "equity": 10842.10,
  "drawdown": 0.012
}
```

## Failure handling
- **Missing derivatives data** for a token → its funding-shadow score is neutral
  (0.0), never dropped; momentum still ranks it.
- **x402 spend cap reached** mid-tick → hold the current book this tick, journal
  the reason, retry next tick. Never trade on partial data.
- **No positive-score names** or **risk-off** → hold/raise stable; a flat tick is
  a valid decision.
- **Journal/identity layer down** → swallow and log; the trade loop must never halt
  on a journaling failure (the record layer is additive, not load-bearing).
- **Breaker trip** → flatten to stable, pause the main loop, require operator
  re-arm before resuming.

## Backtest gate
Do not trade live until a historical backtest shows **max drawdown < 25%**
(30% cap less a 5% margin) for the active preset. Reference synthetic-stress run:
conservative +7.2% / maxDD 8.9%, aggressive +8.6% / maxDD 9.6%.
