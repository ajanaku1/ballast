"""CoinMarketCap data client — x402 pay-per-query.

Each tick buys only the data it needs (funding/OI, Fear & Greed, price/vol) via
the keyless x402 MCP endpoint, settling micro-payments through the agentcash
USDC-on-Base wallet. When no network/credentials are present the client returns
deterministic synthetic data so the pipeline and tests run offline.

The real x402 calls go through the `agentcash` MCP `fetch` tool at runtime; this
module keeps a narrow seam (`_x402_get`) so that wiring is a single swap-in.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from .models import MarketSnapshot, TokenSnapshot


@dataclass
class CMCConfig:
    mcp_url: str = "https://api.coinmarketcap.com/x402/mcp"
    api_key: str | None = None
    spend_cap_usd: float = 5.0
    offline: bool = True  # synthetic data when True


class SpendCapError(RuntimeError):
    """Raised when a tick's x402 spend would exceed the configured cap."""


class CMCClient:
    """Pay-per-query market data. Tracks spend so a tick can't overspend."""

    def __init__(self, cfg: CMCConfig | None = None) -> None:
        self.cfg = cfg or CMCConfig()
        self._spent_usd = 0.0

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    def reset_spend(self) -> None:
        self._spent_usd = 0.0

    # --- public perception API (only what a tick needs) ---
    def fetch_snapshot(self, symbols: list[str], timestamp: float) -> MarketSnapshot:
        """One consolidated perceive() call: BTC regime inputs, F&G, per-token data."""
        btc_price, btc_ma = self._fetch_btc_regime()
        fng = self._fetch_fear_greed()
        tokens = tuple(self._fetch_token(sym, timestamp) for sym in symbols)
        return MarketSnapshot(
            timestamp=timestamp,
            btc_price=btc_price,
            btc_ma=btc_ma,
            fear_greed=fng,
            tokens=tokens,
        )

    # --- per-endpoint (each is a metered x402 request when live) ---
    def _fetch_btc_regime(self) -> tuple[float, float]:
        data = self._x402_get("derivatives/btc-regime", price_usd=0.01)
        return data["price"], data["ma"]

    def _fetch_fear_greed(self) -> int:
        data = self._x402_get("fear-and-greed", price_usd=0.005)
        return int(data["value"])

    def _fetch_token(self, symbol: str, timestamp: float) -> TokenSnapshot:
        data = self._x402_get(f"token/{symbol}", price_usd=0.01)
        return TokenSnapshot(
            symbol=symbol,
            address=data["address"],
            price=data["price"],
            return_24h=data["return_24h"],
            realized_vol=data["realized_vol"],
            funding_rate=data.get("funding_rate"),
            open_interest=data.get("open_interest"),
            oi_change_24h=data.get("oi_change_24h"),
        )

    # --- x402 transport seam ---
    def _x402_get(self, path: str, price_usd: float) -> dict:
        """Single point where a real x402/MCP fetch is wired in.

        Live path (wired at runtime via agentcash MCP):
            resp = agentcash.fetch(url=f"{self.cfg.mcp_url}/{path}")
        Here we meter spend and, offline, synthesise deterministic data.
        """
        if self._spent_usd + price_usd > self.cfg.spend_cap_usd:
            raise SpendCapError(
                f"x402 spend cap {self.cfg.spend_cap_usd} reached at '{path}'"
            )
        self._spent_usd += price_usd
        if self.cfg.offline:
            return _synthetic(path)
        raise NotImplementedError(
            "Live x402 fetch is wired at runtime via the agentcash MCP fetch tool."
        )


def _synthetic(path: str) -> dict:
    """Deterministic pseudo-data keyed on the request path (offline/tests)."""
    h = int(hashlib.sha256(path.encode()).hexdigest(), 16)

    def unit(salt: int) -> float:  # 0..1 deterministic
        return ((h >> salt) & 0xFFFF) / 0xFFFF

    if path == "derivatives/btc-regime":
        price = 50_000 + unit(0) * 20_000
        ma = price * (0.85 + unit(8) * 0.1)  # MA 5-15% below price -> risk-on demo
        return {"price": price, "ma": ma}
    if path == "fear-and-greed":
        return {"value": int(unit(0) * 100)}
    if path.startswith("token/"):
        sym = path.split("/", 1)[1]
        return {
            "address": "0x" + hashlib.sha256(sym.encode()).hexdigest()[:40],
            "price": 0.1 + unit(0) * 100,
            "return_24h": (unit(4) - 0.5) * 0.4,  # +/-20%
            "realized_vol": 0.2 + unit(12) * 1.3,  # 20%..150%
            "funding_rate": (unit(16) - 0.5) * 0.002,  # +/-0.1%
            "open_interest": unit(20) * 1e8,
            "oi_change_24h": (unit(24) - 0.5) * 0.6,
        }
    return {}


def from_env(offline: bool | None = None) -> CMCClient:
    api_key = os.getenv("CMC_API_KEY") or None
    if offline is None:
        # Online only when a key is present AND we're not in paper mode.
        offline = api_key is None or os.getenv("BALLAST_MODE", "paper") == "paper"
    return CMCClient(
        CMCConfig(
            mcp_url=os.getenv("CMC_MCP_URL", CMCConfig.mcp_url),
            api_key=api_key,
            spend_cap_usd=float(os.getenv("X402_SPEND_CAP_USD", "5.0")),
            offline=offline,
        )
    )
