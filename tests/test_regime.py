"""Regime gate: BTC below its ~150h MA flips the whole book to stablecoin."""

from __future__ import annotations

from ballast.models import Regime
from ballast.regime import evaluate


def test_btc_above_ma_is_risk_on(snapshot):
    assert evaluate(snapshot(btc_price=60_000, btc_ma=55_000)) is Regime.RISK_ON


def test_btc_below_ma_is_risk_off(snapshot):
    assert evaluate(snapshot(btc_price=50_000, btc_ma=55_000)) is Regime.RISK_OFF


def test_btc_at_ma_is_risk_off_conservative(snapshot):
    # exactly at the MA: treat as risk-off (survival-biased, no edge to be long)
    assert evaluate(snapshot(btc_price=55_000, btc_ma=55_000)) is Regime.RISK_OFF
