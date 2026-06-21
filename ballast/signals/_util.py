"""Small shared numeric helpers for signals."""

from __future__ import annotations

from statistics import mean, pstdev


def zscore(raw: dict[str, float]) -> dict[str, float]:
    """Cross-sectional z-scores. Returns zeros when there's no dispersion."""
    if not raw:
        return {}
    mu = mean(raw.values())
    sigma = pstdev(raw.values())
    if sigma == 0:
        return {k: 0.0 for k in raw}
    return {k: (v - mu) / sigma for k, v in raw.items()}
