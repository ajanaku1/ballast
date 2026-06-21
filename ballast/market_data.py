"""Real market-data client with multi-source fallback.

Drop-in for the synthetic CMCClient (same `fetch_snapshot` surface), sourced from
free public APIs so the agent runs on real BSC-market data with no API key and no
x402 spend. It tries sources in order and uses the first that returns data, so a
single venue being blocked (Binance is geo-restricted from many networks) doesn't
idle the agent:

  1. Binance  — funding (perps) + price/24h/vol (spot) + BTC klines
  2. CoinGecko — funding+OI (/derivatives) + price/24h (/coins/markets) + BTC chart

Fear & Greed comes from alternative.me (independent), with a neutral fallback.
Tokens without coverage degrade gracefully: no funding → neutral funding-shadow
(momentum still ranks them); no price → excluded from the tick.
"""

from __future__ import annotations

import math

import requests

from .models import MarketSnapshot, TokenSnapshot

_TIMEOUT = 12
_MIN_VOL = 0.05  # floor so inverse-vol sizing never divides by ~0
_FNG = "https://api.alternative.me/fng/?limit=1"
# Stablecoins aren't basket candidates and their cross-exchange "funding" is noise
# that would distort the cross-sectional funding-shadow z-score — drop it.
_STABLES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "BUSD", "USDD", "FRAX",
            "USDE", "USD1", "PYUSD", "USDP", "LISUSD", "FRXUSD", "USDF", "DUSD"}


class AllSourcesFailed(RuntimeError):
    """Raised when every market-data source is unreachable for a tick."""


class MarketDataClient:
    def __init__(self, quote: str = "USDT", btc_ma_hours: int = 150) -> None:
        self.quote = quote
        self.btc_ma_hours = btc_ma_hours
        self._spent_usd = 0.0  # free sources; kept for interface parity
        self.last_source = "none"

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    def reset_spend(self) -> None:
        self._spent_usd = 0.0

    def fetch_snapshot(self, symbols: list[str], timestamp: float) -> MarketSnapshot:
        fng = self._fear_greed()
        errors = []
        for name, source in (("binance", self._binance), ("coingecko", self._coingecko)):
            try:
                tokens, btc_price, btc_ma = source(symbols)
            except Exception as exc:  # noqa: BLE001 — try the next source
                errors.append(f"{name}: {type(exc).__name__}")
                continue
            if tokens:
                self.last_source = name
                return MarketSnapshot(timestamp, btc_price, btc_ma, fng, tuple(tokens))
            errors.append(f"{name}: no tokens")
        raise AllSourcesFailed("; ".join(errors))

    # --- source 1: Binance (batched) ---
    def _binance(self, symbols: list[str]) -> tuple[list[TokenSnapshot], float, float]:
        spot = "https://api.binance.com/api/v3"
        tickers = {r["symbol"]: r for r in
                   requests.get(f"{spot}/ticker/24hr", timeout=_TIMEOUT).json()}
        funding = {r["symbol"]: float(r["lastFundingRate"]) for r in
                   requests.get("https://fapi.binance.com/fapi/v1/premiumIndex",
                                timeout=_TIMEOUT).json() if r.get("lastFundingRate")}
        kl = requests.get(f"{spot}/klines", timeout=_TIMEOUT, params={
            "symbol": f"BTC{self.quote}", "interval": "1h", "limit": self.btc_ma_hours}).json()
        closes = [float(c[4]) for c in kl]
        btc_ma = sum(closes) / len(closes) if closes else 0.0
        btc_price = float(tickers.get(f"BTC{self.quote}", {}).get("lastPrice", closes[-1]))

        tokens = []
        for sym in symbols:
            tk = tickers.get(f"{sym}{self.quote}")
            if not tk:
                continue
            tokens.append(TokenSnapshot(
                symbol=sym, address="", price=float(tk["lastPrice"]),
                return_24h=float(tk["priceChangePercent"]) / 100.0,
                realized_vol=_parkinson(float(tk.get("highPrice", 0)), float(tk.get("lowPrice", 0))),
                funding_rate=funding.get(f"{sym}{self.quote}"),
                open_interest=None, oi_change_24h=None))
        return tokens, btc_price, btc_ma

    # --- source 2: CoinGecko (batched, works where exchanges are blocked) ---
    def _coingecko(self, symbols: list[str]) -> tuple[list[TokenSnapshot], float, float]:
        cg = "https://api.coingecko.com/api/v3"
        markets = requests.get(f"{cg}/coins/markets", timeout=_TIMEOUT, params={
            "vs_currency": "usd", "order": "market_cap_desc",
            "per_page": 250, "page": 1}).json()
        by_symbol: dict[str, dict] = {}
        for m in markets:  # first (highest mcap) wins on symbol collision
            by_symbol.setdefault(m["symbol"].upper(), m)

        funding = self._coingecko_funding(cg)

        chart = requests.get(f"{cg}/coins/bitcoin/market_chart", timeout=_TIMEOUT, params={
            "vs_currency": "usd", "days": 7, "interval": "hourly"}).json()
        closes = [p[1] for p in chart.get("prices", [])][-self.btc_ma_hours:]
        btc_ma = sum(closes) / len(closes) if closes else 0.0
        btc_price = closes[-1] if closes else by_symbol.get("BTC", {}).get("current_price", 0.0)

        tokens = []
        for sym in symbols:
            m = by_symbol.get(sym.upper())
            if not m or not m.get("current_price"):
                continue
            tokens.append(TokenSnapshot(
                symbol=sym, address="", price=float(m["current_price"]),
                return_24h=(m.get("price_change_percentage_24h") or 0.0) / 100.0,
                realized_vol=_parkinson(m.get("high_24h") or 0.0, m.get("low_24h") or 0.0),
                funding_rate=funding.get(sym.upper()),
                open_interest=None, oi_change_24h=None))
        return tokens, btc_price, btc_ma

    def _coingecko_funding(self, cg: str) -> dict[str, float]:
        """Best-effort funding per base symbol from CoinGecko's cross-exchange
        derivatives feed: pick each symbol's most-liquid (max open-interest) venue.
        Absolute units don't matter — the funding-shadow signal is cross-sectional."""
        try:
            rows = requests.get(f"{cg}/derivatives", timeout=_TIMEOUT).json()
        except Exception:  # noqa: BLE001
            return {}
        best: dict[str, tuple[float, float]] = {}  # base -> (open_interest, funding)
        for r in rows:
            base = _base_symbol(r.get("symbol", ""))
            fr, oi = r.get("funding_rate"), r.get("open_interest")
            if not base or base in _STABLES or fr is None:
                continue
            oi = float(oi or 0.0)
            if base not in best or oi > best[base][0]:
                best[base] = (oi, float(fr))
        return {b: f for b, (_, f) in best.items()}

    def _fear_greed(self) -> int:
        try:
            return int(requests.get(_FNG, timeout=_TIMEOUT).json()["data"][0]["value"])
        except Exception:  # noqa: BLE001 — neutral if the index is unreachable
            return 50


def _parkinson(hi: float, lo: float) -> float:
    """Annualised realized-vol proxy from the 24h high/low (Parkinson estimator)."""
    if hi <= 0 or lo <= 0 or hi <= lo:
        return _MIN_VOL
    return max(_MIN_VOL, (math.log(hi / lo) / math.sqrt(4 * math.log(2))) * math.sqrt(365))


def _base_symbol(sym: str) -> str:
    """'BNBUSDT' / 'BNB-PERP' / 'BNBUSD' -> 'BNB'. Empty if not a USD(T) pair."""
    s = sym.upper().replace("-", "").replace("_", "")
    for quote in ("USDT", "USD", "PERP", "USDC"):
        if s.endswith(quote) and len(s) > len(quote):
            return s[: -len(quote)]
    return ""
