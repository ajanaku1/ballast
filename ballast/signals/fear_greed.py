"""Fear & Greed gross-exposure throttle (contrarian).

The index sets *how much* of the book is deployed, not *what* it holds. We lean
contrarian: extreme fear (0) opens exposure to the configured max, extreme greed
(100) closes it toward the min. Froth is where naked momentum agents breach the
drawdown gate; throttling down into greed is part of the survival overlay. The
BTC regime gate handles the falling-knife side, so being more invested in fear is
safe within risk-on.
"""

from __future__ import annotations


def exposure(fear_greed: int, min_gross: float, max_gross: float) -> float:
    fng = max(0, min(100, fear_greed))
    return max_gross - (fng / 100.0) * (max_gross - min_gross)
