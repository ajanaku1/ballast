"""Shared test fixtures."""

from __future__ import annotations

import pytest

from ballast.models import MarketSnapshot, TokenSnapshot


def tok(symbol, price=1.0, return_24h=0.0, realized_vol=0.5,
        funding_rate=None, open_interest=None, oi_change_24h=None):
    return TokenSnapshot(
        symbol=symbol,
        address="0x" + symbol.encode().hex().ljust(40, "0")[:40],
        price=price,
        return_24h=return_24h,
        realized_vol=realized_vol,
        funding_rate=funding_rate,
        open_interest=open_interest,
        oi_change_24h=oi_change_24h,
    )


@pytest.fixture
def make_token():
    return tok


@pytest.fixture
def snapshot(make_token):
    def _make(btc_price=60_000, btc_ma=55_000, fear_greed=50, tokens=None):
        return MarketSnapshot(
            timestamp=0.0,
            btc_price=btc_price,
            btc_ma=btc_ma,
            fear_greed=fear_greed,
            tokens=tuple(tokens or ()),
        )

    return _make
