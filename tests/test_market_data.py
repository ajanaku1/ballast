"""Multi-source market-data tests: symbol parsing, vol proxy, fallback ordering."""

from __future__ import annotations

import pytest

from ballast.market_data import MarketDataClient, AllSourcesFailed, _base_symbol, _parkinson
from ballast.models import TokenSnapshot


def test_base_symbol_strips_quote():
    assert _base_symbol("BNBUSDT") == "BNB"
    assert _base_symbol("BTC-PERP") == "BTC"
    assert _base_symbol("ETHUSD") == "ETH"
    assert _base_symbol("CAKE_USDC") == "CAKE"
    assert _base_symbol("NOTAPAIR") == ""  # no recognised quote


def test_parkinson_vol_floor_and_monotonicity():
    assert _parkinson(0, 0) == 0.05          # degenerate -> floor
    assert _parkinson(100, 100) == 0.05      # hi == lo -> floor
    wide = _parkinson(110, 90)
    narrow = _parkinson(101, 99)
    assert wide > narrow > 0.05              # wider range -> higher vol


def _tok(sym):
    return TokenSnapshot(symbol=sym, address="", price=1.0, return_24h=0.0, realized_vol=0.5)


def test_fallback_uses_second_source_when_first_fails(monkeypatch):
    c = MarketDataClient()
    monkeypatch.setattr(c, "_fear_greed", lambda: 50)
    monkeypatch.setattr(c, "_binance", lambda syms: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(c, "_coingecko", lambda syms: ([_tok("BNB")], 100.0, 90.0))
    snap = c.fetch_snapshot(["BNB"], 0.0)
    assert c.last_source == "coingecko"
    assert [t.symbol for t in snap.tokens] == ["BNB"]
    assert snap.btc_price > snap.btc_ma  # risk-on inputs preserved


def test_first_source_wins_when_available(monkeypatch):
    c = MarketDataClient()
    monkeypatch.setattr(c, "_fear_greed", lambda: 40)
    monkeypatch.setattr(c, "_binance", lambda syms: ([_tok("ETH")], 100.0, 95.0))
    monkeypatch.setattr(c, "_coingecko", lambda syms: ([_tok("BNB")], 1.0, 1.0))
    snap = c.fetch_snapshot(["ETH"], 0.0)
    assert c.last_source == "binance"
    assert [t.symbol for t in snap.tokens] == ["ETH"]


def test_all_sources_failed_raises(monkeypatch):
    c = MarketDataClient()
    monkeypatch.setattr(c, "_fear_greed", lambda: 50)
    boom = lambda syms: (_ for _ in ()).throw(RuntimeError("down"))
    monkeypatch.setattr(c, "_binance", boom)
    monkeypatch.setattr(c, "_coingecko", boom)
    with pytest.raises(AllSourcesFailed):
        c.fetch_snapshot(["BNB"], 0.0)
