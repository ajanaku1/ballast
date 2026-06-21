"""Cross-sectional momentum: rank the universe by recent return.

Plain and robust — z-scored 24h return. Blended with funding-shadow so the basket
favours names that both the leverage crowd is short *and* price is confirming.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import TokenSnapshot
from ._util import zscore


def score(tokens: Iterable[TokenSnapshot]) -> dict[str, float]:
    raw = {t.symbol: t.return_24h for t in tokens}
    return zscore(raw)
