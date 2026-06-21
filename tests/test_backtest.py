"""Backtest gate tests: the overlay holds DD under cap, and the breaker is a
working backstop (fires when the regime gate is switched off in a crash)."""

from __future__ import annotations

from dataclasses import replace

from ballast.config import Config, Preset
from backtest.backtest import run, synthetic_panel, max_drawdown


def test_gate_passes_both_presets():
    snaps = synthetic_panel()
    for preset in (Preset.CONSERVATIVE, Preset.AGGRESSIVE):
        r = run(snaps, Config.from_preset(preset))
        assert r.passes_gate(), f"{preset} maxDD {r.max_drawdown:.1%} breached gate"


def test_breaker_fires_when_regime_gate_disabled():
    # Strip the first line of defence; the independent breaker must still cap DD.
    cfg = Config.from_preset(Preset.CONSERVATIVE)
    cfg = cfg.replace(signals=replace(cfg.signals, regime_gate=False))
    r = run(synthetic_panel(), cfg)
    assert r.breaker_fired
    assert r.max_drawdown < 0.30  # never reaches the DQ line


def test_max_drawdown_helper():
    assert max_drawdown([100, 120, 90]) == 0.25
    assert max_drawdown([100, 110, 121]) == 0.0
