"""Stage 3+4 orchestration: snapshot -> target basket.

Shared by the live loop and the backtest so both exercise *identical* decision
logic. Pure: no I/O, no chain. Given a perceived market and a config, return the
desired portfolio (per-token weights + gross exposure + regime).
"""

from __future__ import annotations

from .config import Config
from .models import MarketSnapshot, Regime, TargetBasket
from .regime import evaluate
from .risk import inverse_vol_weights
from .signals import blend, select_basket
from .signals import funding_shadow, momentum
from .signals.fear_greed import exposure


def build_target(snapshot: MarketSnapshot, cfg: Config) -> TargetBasket:
    sig = cfg.signals
    regime = evaluate(snapshot) if sig.regime_gate else Regime.RISK_ON
    if regime is Regime.RISK_OFF:
        return TargetBasket({}, 0.0, regime, cfg.stable_symbol)

    blended = _blended_scores(snapshot, cfg)
    basket = select_basket(blended, cfg.limits.basket_size)
    if not basket:
        return TargetBasket({}, 0.0, regime, cfg.stable_symbol)

    gross = _gross_exposure(snapshot, cfg)
    vols = {t.symbol: t.realized_vol for t in snapshot.tokens if t.symbol in basket}
    weights = inverse_vol_weights(vols, gross, cfg.limits.max_token_weight)
    return TargetBasket(weights, sum(weights.values()), regime, cfg.stable_symbol)


def blended_scores(snapshot: MarketSnapshot, cfg: Config) -> dict[str, float]:
    """Public view of the combined signal scores — the decision rationale the
    journal and dashboard record. Same computation `build_target` ranks on."""
    return _blended_scores(snapshot, cfg)


def _blended_scores(snapshot: MarketSnapshot, cfg: Config) -> dict[str, float]:
    sig = cfg.signals
    funding = funding_shadow.score(snapshot.tokens) if sig.funding_shadow else {}
    mom = momentum.score(snapshot.tokens) if sig.momentum else {}
    # Collapse the blend weight to whichever signals are actually enabled.
    if sig.funding_shadow and not sig.momentum:
        fw = 1.0
    elif sig.momentum and not sig.funding_shadow:
        fw = 0.0
    else:
        fw = cfg.limits.funding_weight
    return blend(funding, mom, fw)


def _gross_exposure(snapshot: MarketSnapshot, cfg: Config) -> float:
    if not cfg.signals.fear_greed_throttle:
        return cfg.limits.max_gross_exposure
    return exposure(
        snapshot.fear_greed,
        cfg.limits.min_gross_exposure,
        cfg.limits.max_gross_exposure,
    )
