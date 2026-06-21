"""Execution tests: trade diffing and paper-fill application."""

from __future__ import annotations

import math

from ballast.config import Config
from ballast.execute import diff_to_trades, Executor
from ballast.models import TargetBasket
from ballast.state import seed_state
from ballast.twak_client import TwakClient


def _target(weights, stable="USDT"):
    return TargetBasket(weights, sum(weights.values()), regime=None, stable_symbol=stable)  # type: ignore[arg-type]


def test_diff_enters_from_flat():
    trades = diff_to_trades({}, _target({"A": 0.5, "B": 0.3}), equity=1000, stable="USDT")
    assert all(t.sell_symbol == "USDT" for t in trades)
    assert {t.buy_symbol for t in trades} == {"A", "B"}
    assert math.isclose(sum(t.usd_amount for t in trades), 800.0)


def test_diff_sells_before_buys():
    trades = diff_to_trades({"A": 0.6}, _target({"B": 0.6}), equity=1000, stable="USDT")
    assert trades[0].sell_symbol == "A"      # exit first
    assert trades[-1].buy_symbol == "B"      # enter after


def test_diff_suppresses_dust():
    trades = diff_to_trades({"A": 0.5}, _target({"A": 0.5001}), equity=1000, stable="USDT")
    assert trades == []


def test_executor_paper_fill_moves_state():
    cfg = Config()
    state = seed_state(1000.0)
    ex = Executor(TwakClient(), state, cfg)
    ex.rebalance(_target({"A": 0.5}), prices={"A": 2.0, "USDT": 1.0})
    assert "A" in state.positions
    assert math.isclose(state.positions["A"].value, 500.0, rel_tol=1e-6)
    assert math.isclose(state.cash, 500.0, rel_tol=1e-6)


def test_thin_capital_lowers_min_trade():
    from ballast.config import Config
    cfg = Config.for_thin_capital()
    assert cfg.min_trade_usd < 1.0
    assert cfg.limits.basket_size == 3
    # a $0.20 delta on a $5 book = $1.00 -> would be suppressed at default $1 min,
    # but allowed under thin-capital's lower threshold
    trades = diff_to_trades({}, _target({"A": 0.2}), equity=5.0, stable="USDT",
                            min_trade_usd=cfg.min_trade_usd)
    assert len(trades) == 1


def test_explicit_buy_for_activity_heartbeat():
    cfg = Config().replace(min_trade_usd=0.10)
    state = seed_state(2.0)
    ex = Executor(TwakClient(), state, cfg)
    rec = ex.buy("CAKE", 0.25, price=2.0, reason="heartbeat (activity)")
    assert rec["buy"] == "CAKE" and rec["reason"] == "heartbeat (activity)"
    assert "CAKE" in state.positions


def test_flatten_returns_to_stable():
    cfg = Config()
    state = seed_state(1000.0)
    ex = Executor(TwakClient(), state, cfg)
    ex.rebalance(_target({"A": 0.5}), prices={"A": 2.0, "USDT": 1.0})
    ex.flatten(prices={"A": 2.0, "USDT": 1.0})
    assert state.positions == {}
    assert math.isclose(state.cash, 1000.0, rel_tol=1e-6)
