"""Config layer: one engine, many personalities.

A preset selects the risk posture; toggles turn signals on/off; autonomy level
decides whether the agent self-signs or routes through a human (WalletConnect).
Everything the strategy and risk overlay need to behave differently lives here —
no magic numbers buried in logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


class Preset(str, Enum):
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"


class Autonomy(str, Enum):
    AUTONOMOUS = "autonomous"  # self-signing, no human in loop
    HUMAN_IN_LOOP = "human_in_loop"  # TWAK WalletConnect confirmation


class Mode(str, Enum):
    PAPER = "paper"  # no chain, simulated fills
    DRY_RUN = "dry_run"  # build txns, log, do not broadcast
    LIVE = "live"  # broadcast real swaps (gated)


@dataclass(frozen=True)
class SignalToggles:
    funding_shadow: bool = True
    momentum: bool = True
    fear_greed_throttle: bool = True
    regime_gate: bool = True


@dataclass(frozen=True)
class RiskLimits:
    """The survival-first overlay's knobs. The product lives here."""

    # Internal self-kill, set well inside the 30% DQ line.
    breaker_drawdown: float = 0.15
    # Per-token weight ceiling so no single name can blow the cap.
    max_token_weight: float = 0.20
    # Gross exposure band the Fear & Greed dial moves within.
    min_gross_exposure: float = 0.40
    max_gross_exposure: float = 1.00
    # Annualised portfolio vol target for the inverse-vol scaler.
    vol_target: float = 0.50
    # How many top-ranked tokens to hold.
    basket_size: int = 8
    # Blend weight: funding-shadow vs momentum (0..1, weight on funding).
    funding_weight: float = 0.5


# Risk posture per preset. Aggressive runs a looser self-kill and more exposure.
_PRESET_LIMITS: dict[Preset, RiskLimits] = {
    Preset.CONSERVATIVE: RiskLimits(
        breaker_drawdown=0.15,
        max_token_weight=0.20,
        min_gross_exposure=0.40,
        max_gross_exposure=0.90,
        vol_target=0.40,
        basket_size=8,
        funding_weight=0.5,
    ),
    Preset.AGGRESSIVE: RiskLimits(
        breaker_drawdown=0.25,
        max_token_weight=0.30,
        min_gross_exposure=0.50,
        max_gross_exposure=1.00,
        vol_target=0.65,
        basket_size=12,
        funding_weight=0.6,
    ),
}


@dataclass(frozen=True)
class Config:
    preset: Preset = Preset.CONSERVATIVE
    autonomy: Autonomy = Autonomy.AUTONOMOUS
    mode: Mode = Mode.PAPER
    signals: SignalToggles = field(default_factory=SignalToggles)
    limits: RiskLimits = field(default_factory=RiskLimits)

    # Cadence (seconds). Main tick ~hourly; breaker ~every few minutes.
    tick_interval_s: int = 3600
    breaker_interval_s: int = 180

    # Regime gate: BTC moving-average window (hours).
    btc_ma_hours: int = 150

    # x402 per-tick spend cap (USD).
    x402_spend_cap_usd: float = 5.0

    stable_symbol: str = "USDT"
    # All assets treated as stable (excluded from the basket and not churned
    # against each other) — lets the activity heartbeat rotate between stables.
    stable_symbols: tuple[str, ...] = ("USDT", "USDC")

    # Minimum swap size (USD) — suppresses dust churn. Lower it for thin capital
    # so daily rebalances aren't all suppressed (gas is sponsored, so the only
    # cost per trade is ~0.6% DEX slippage; don't churn below what's worth it).
    min_trade_usd: float = 1.0
    # Force one minimal "heartbeat" trade if a day would otherwise be flat, to
    # satisfy the >=1-trade/day activity rule. 0 disables.
    heartbeat_trade_usd: float = 0.0

    @staticmethod
    def from_preset(preset: Preset, **overrides) -> "Config":
        limits = _PRESET_LIMITS[preset]
        cfg = Config(preset=preset, limits=limits)
        return cfg.replace(**overrides) if overrides else cfg

    @staticmethod
    def for_thin_capital(preset: Preset = Preset.CONSERVATIVE) -> "Config":
        """Tuning for a small (~$1–20) gasless wallet: tiny min-trade so daily
        rebalances aren't all suppressed, a concentrated low-slippage basket, and
        a heartbeat trade to keep the activity streak alive. Gas is sponsored, so
        the only per-trade cost is DEX slippage — keep trades few and liquid."""
        from dataclasses import replace as _replace

        cfg = Config.from_preset(preset)
        thin_limits = _replace(cfg.limits, basket_size=3, max_token_weight=0.40)
        return cfg.replace(limits=thin_limits, min_trade_usd=0.10,
                           heartbeat_trade_usd=0.25)

    @staticmethod
    def from_env() -> "Config":
        preset = Preset(os.getenv("BALLAST_PRESET", "conservative").lower())
        cfg = Config.from_preset(preset)
        mode = Mode(os.getenv("BALLAST_MODE", "paper").lower())
        cap = float(os.getenv("X402_SPEND_CAP_USD", cfg.x402_spend_cap_usd))
        return cfg.replace(mode=mode, x402_spend_cap_usd=cap)

    def replace(self, **changes) -> "Config":
        from dataclasses import replace as _replace

        return _replace(self, **changes)
