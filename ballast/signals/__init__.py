"""Signal blending and basket selection.

Stage 3 of the tick: combine funding-shadow and momentum into one cross-sectional
score, then pick the top-N positively-ranked names (long-only).
"""

from __future__ import annotations


def blend(funding: dict[str, float], momentum: dict[str, float],
          funding_weight: float) -> dict[str, float]:
    """Weighted blend of two z-scored signals. funding_weight in [0, 1]."""
    fw = max(0.0, min(1.0, funding_weight))
    symbols = set(funding) | set(momentum)
    return {
        s: fw * funding.get(s, 0.0) + (1.0 - fw) * momentum.get(s, 0.0)
        for s in symbols
    }


def select_basket(blended: dict[str, float], n: int) -> list[str]:
    """Top-n symbols by score, positives only (no shorting, no dead weight)."""
    ranked = sorted(blended.items(), key=lambda kv: kv[1], reverse=True)
    return [s for s, v in ranked[:n] if v > 0.0]
