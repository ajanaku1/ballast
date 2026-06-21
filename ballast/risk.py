"""Stage 4: position sizing — the heart of the survival overlay.

Inverse-volatility weights so calmer names carry more of the book; a hard
per-token cap so no single token can blow the drawdown budget; excess from capped
names redistributed to the uncapped; the whole book scaled to the gross exposure
the Fear & Greed throttle allows. Anything that can't be deployed under the cap
stays in the stable asset — never force-fit risk to hit a gross target.
"""

from __future__ import annotations


def inverse_vol_weights(vols: dict[str, float], gross: float, cap: float) -> dict[str, float]:
    """Map {symbol: realized_vol} to {symbol: weight}.

    weights are fractions of total equity, each <= cap, summing to at most
    `gross` (less when the cap can't absorb the full gross across the basket).
    """
    if not vols:
        return {}
    if any(v <= 0 for v in vols.values()):
        raise ValueError("realized vol must be positive for every basket member")

    # Inverse-vol, normalised to the gross target.
    inv = {s: 1.0 / v for s, v in vols.items()}
    z = sum(inv.values())
    weights = {s: gross * iv / z for s, iv in inv.items()}

    return _apply_cap(weights, cap)


def _apply_cap(weights: dict[str, float], cap: float) -> dict[str, float]:
    """Clamp to `cap`, redistributing freed weight to uncapped names by their
    relative size. Iterates to a fixed point; if everything caps, the residual
    is simply left undeployed (held in stable)."""
    capped: dict[str, float] = {}
    remaining = dict(weights)

    while remaining:
        over = {s: w for s, w in remaining.items() if w > cap + 1e-12}
        if not over:
            capped.update(remaining)
            break
        excess = sum(remaining[s] - cap for s in over)
        for s in over:
            capped[s] = cap
            del remaining[s]
        if not remaining:  # nowhere to put the excess — leave it in stable
            break
        pool = sum(remaining.values())
        if pool <= 0:
            break
        for s in remaining:
            remaining[s] += excess * remaining[s] / pool

    return capped
