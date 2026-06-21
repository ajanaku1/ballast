"""Real market-data client — live funding/OI, price, vol, Fear & Greed.

Drop-in replacement for the synthetic `CMCClient`: same `fetch_snapshot(symbols,
timestamp)` surface, but sourced from live public APIs so the agent runs on real
BSC-market data with no API key and no x402 spend:

  - funding rate (the funding-shadow signal) ← Binance USDⓈ-M perps (batch)
  - price + 24h return + realized-vol proxy   ← Binance spot 24h ticker (batch)
  - Fear & Greed index                         ← alternative.me (free)
  - BTC price + ~150h MA (regime gate)         ← Binance 1h klines

Tokens without a Binance market degrade gracefully: no funding → neutral signal;
no price → excluded from this tick (we can't size or trade what we can't price).
The paid CMC x402 path remains available in `cmc_client` for when USDC is funded.
"""

from __future__ import annotations

import math

import requests

from .models import MarketSnapshot, TokenSnapshot

_SPOT = "https://api.binance.com/api/v3"
_FUT = "https://fapi.binance.com/fapi/v1"
_FNG = "https://api.alternative.me/fng/?limit=1"
_TIMEOUT = 12
_MIN_VOL = 0.05  # floor so inverse-vol sizing never divides by ~0


class MarketDataClient:
    """Live data with the same interface the pipeline expects."""

    def __init__(self, quote: str = "USDT", btc_ma_hours: int = 150) -> None:
        self.quote = quote
        self.btc_ma_hours = btc_ma_hours
        self._spent_usd = 0.0  # always 0: these sources are free (kept for interface parity)

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    def reset_spend(self) -> None:
        self._spent_usd = 0.0

    def fetch_snapshot(self, symbols: list[str], timestamp: float) -> MarketSnapshot:
        tickers = self._all_tickers()
        funding = self._all_funding()
        btc_price, btc_ma = self._btc_regime(tickers)
        fng = self._fear_greed()

        tokens: list[TokenSnapshot] = []
        for sym in symbols:
            pair = f"{sym}{self.quote}"
            tk = tickers.get(pair)
            if not tk:  # no live price → can't size/trade it this tick
                continue
            tokens.append(TokenSnapshot(
                symbol=sym,
                address="",  # resolved at execution time via twak search
                price=float(tk["lastPrice"]),
                return_24h=float(tk["priceChangePercent"]) / 100.0,
                realized_vol=_parkinson_vol(tk),
                funding_rate=funding.get(pair),
                open_interest=None,
                oi_change_24h=None,
            ))
        return MarketSnapshot(timestamp, btc_price, btc_ma, fng, tuple(tokens))

    # --- batched sources (whole universe in one call each) ---
    def _all_tickers(self) -> dict[str, dict]:
        rows = requests.get(f"{_SPOT}/ticker/24hr", timeout=_TIMEOUT).json()
        return {r["symbol"]: r for r in rows}

    def _all_funding(self) -> dict[str, float]:
        rows = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex",
                            timeout=_TIMEOUT).json()
        return {r["symbol"]: float(r["lastFundingRate"]) for r in rows
                if r.get("lastFundingRate") is not None}

    def _btc_regime(self, tickers: dict) -> tuple[float, float]:
        kl = requests.get(f"{_SPOT}/klines", timeout=_TIMEOUT, params={
            "symbol": f"BTC{self.quote}", "interval": "1h", "limit": self.btc_ma_hours,
        }).json()
        closes = [float(c[4]) for c in kl]
        ma = sum(closes) / len(closes) if closes else 0.0
        price = float(tickers.get(f"BTC{self.quote}", {}).get("lastPrice", closes[-1]))
        return price, ma

    def _fear_greed(self) -> int:
        data = requests.get(_FNG, timeout=_TIMEOUT).json()
        return int(data["data"][0]["value"])


def _parkinson_vol(ticker: dict) -> float:
    """Annualised realized-vol proxy from the 24h high/low (Parkinson estimator)."""
    hi, lo = float(ticker.get("highPrice", 0)), float(ticker.get("lowPrice", 0))
    if hi <= 0 or lo <= 0 or hi <= lo:
        return _MIN_VOL
    daily = math.log(hi / lo) / math.sqrt(4 * math.log(2))
    return max(_MIN_VOL, daily * math.sqrt(365))
