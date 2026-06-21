"""Stage 1: perceive — buy only the data this tick needs, via x402.

Thin orchestration over `CMCClient`: fetch BTC regime inputs, Fear & Greed, and
per-token price/vol/funding/OI for the competition universe, metered per request
so a tick can't overspend its x402 cap. Returns a `MarketSnapshot` the rest of
the pipeline consumes.
"""

from __future__ import annotations

from .cmc_client import CMCClient
from .models import MarketSnapshot


def perceive(client: CMCClient, universe: list[str], timestamp: float) -> MarketSnapshot:
    client.reset_spend()  # fresh per-tick budget
    return client.fetch_snapshot(universe, timestamp)
