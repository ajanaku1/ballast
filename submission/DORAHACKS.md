# Ballast, BNB Hack: AI Trading Agent Edition (DoraHacks submission)

**Agent wallet (BSC):** `0x05e690aE1a0D9865f3d71E28c3e50d56A1ecbd94`
**On-chain registration tx:** [`0xaf9107c9770bd4e7fb7c947d52d739a05c8b051288095b50f247ce79e6db9554`](https://bscscan.com/tx/0xaf9107c9770bd4e7fb7c947d52d739a05c8b051288095b50f247ce79e6db9554)
**Repo:** _<add public repo URL>_
**Demo video:** _<add link>_

## One-liner
Ballast is a self-custody, **spot-only** autonomous trading agent that reads *where leverage is about to break*, using CoinMarketCap derivatives data (funding, open interest) as a **signal** for **spot** execution, wrapped in a survival-first risk overlay built to hold inside the 30% max-drawdown disqualifier.

## The two insights it's built on
1. **The sanctioned stack is spot-only.** Trust Wallet Agent Kit (TWAK) does swaps, not perps. So instead of fighting that, Ballast uses *derivatives data as a signal* and executes in *spot*: it positions before the leverage crowd's unwind without ever touching leverage.
2. **This contest is won by the risk overlay, not the alpha.** Track 1 is ranked on live PnL with a **30% max-drawdown hard disqualifier**, every naked momentum/sentiment bot breaches it. Ballast's overlay is the product: it survives the gate while flashier agents capsize. Hence the name, ballast keeps the ship upright.

## The strategy (how results are produced)
One decision loop, ~hourly, over the fixed 149-token BEP-20 universe:

1. **Perceive**, pay-per-query (x402) for only this tick's data: funding/OI, Fear & Greed, price/vol, BTC.
2. **Regime gate**, if BTC ≤ its ~150-hour moving average, rotate the whole book to a stablecoin and stop. No edge being long a falling market.
3. **Signal**, rank every token by a **funding-shadow** score blended with **cross-sectional momentum**:
   - *funding-shadow:* deeply **negative** funding = crowded shorts = short-squeeze fuel → **bullish** for a spot long entered *before* the cascade; deeply **positive** funding = crowded longs = long-squeeze (downside) risk → bearish. Rising open interest amplifies conviction (more leverage stacked = larger unwind).
   - blended z-scores, top-N positive names only (long-only, no dead weight).
4. **Throttle + size**, Fear & Greed sets gross exposure contrarian (40–100%; fear opens, greed reefs). Within that, **inverse-volatility** weights with a **per-token cap** (excess redistributed) so no single token can blow the drawdown budget.
5. **Execute**, diff target vs current; TWAK signs & swaps only the deltas on BSC, self-custody.
6. **Record**, decision + rationale to a hash-chained, tamper-evident journal under the agent's ERC-8004 identity.

Off the main clock: an **independent drawdown circuit-breaker** (own thread, every few minutes) flattens to stablecoin and pauses the loop at the internal self-kill (15% conservative / 25% aggressive), well inside the 30% line.

## Risk overlay (why it survives the gate)
Inverse-vol sizing · per-token cap · contrarian Fear & Greed throttle · BTC regime kill-switch · independent fast drawdown breaker. Built **test-first**; validated by a backtest gate that requires max drawdown < 25% before any live wiring. Reference synthetic-stress (incl. a leverage cascade): **Conservative +7.2% / maxDD 8.9%**, **Aggressive +8.6% / maxDD 9.6%**.

## Prize surface used (for real, not README claims)
- **Track 1:** autonomous spot agent + risk overlay, registered on-chain (tx above), trading the 149-token universe.
- **Best-Use-of-TWAK:** TWAK is the sole execution layer with autonomous on-device signing; x402 "pay-as-it-thinks" data loop buys only what each tick needs.
- **Best-Use-of-BNB-SDK:** ERC-8004 on-chain identity + a tamper-evident decision journal via the BNB AI Agent SDK, on the **same** wallet, as an additive fail-safe layer that never halts the trade loop.
- **Track 2:** a `SKILL.md` strategy spec (the funding-shadow / liquidation-cascade logic) submitted separately.

## Verifiability
Self-custody throughout (one BSC wallet, OS-keychain signing). Every decision is journaled with its rationale and hash-chained for offline tamper-evidence; the journaling layer is isolated so it can fail without stopping trading.
