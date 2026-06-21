"""Funding-shadow signal — the novel core.

Derivatives data as a *spot* signal. When funding is deeply negative, shorts are
crowded and paying to be short: that is short-squeeze fuel, bullish for a spot
long held *before* the cascade. Deeply positive funding means crowded longs and
long-squeeze (downside) risk, bearish. Rising open interest means more leverage
stacked, so the eventual unwind is larger — it amplifies conviction either way.

Score is cross-sectional (z-scored across the tick's universe); tokens without
derivatives coverage score neutral (0.0).
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import TokenSnapshot
from ._util import zscore


def score(tokens: Iterable[TokenSnapshot]) -> dict[str, float]:
    raw: dict[str, float] = {}
    for t in tokens:
        if t.funding_rate is None:
            continue
        # Bullish when funding negative; amplify by rising OI (leverage building).
        oi_amp = 1.0 + max(0.0, t.oi_change_24h or 0.0)
        raw[t.symbol] = -t.funding_rate * oi_amp

    z = zscore(raw)
    # Tokens lacking funding data are explicitly neutral, not dropped.
    return {t.symbol: z.get(t.symbol, 0.0) for t in tokens}
