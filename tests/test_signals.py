"""Signal tests: funding-shadow, momentum, blend/select, Fear&Greed throttle.

Thesis under test: negative funding (crowded shorts → short-squeeze fuel) is
*bullish* for a spot long; positive funding (crowded longs → long-squeeze risk)
is bearish. Momentum is plain cross-sectional 24h return. F&G throttle is
contrarian: fear opens exposure, greed closes it.
"""

from __future__ import annotations

import math

from ballast.signals import funding_shadow, momentum
from ballast.signals import blend, select_basket
from ballast.signals.fear_greed import exposure


# --- funding-shadow ---
def test_funding_shadow_negative_funding_is_bullish(make_token):
    toks = [
        make_token("SHORTS", funding_rate=-0.001, oi_change_24h=0.2),  # crowded shorts
        make_token("LONGS", funding_rate=0.001, oi_change_24h=0.2),    # crowded longs
        make_token("FLAT", funding_rate=0.0, oi_change_24h=0.0),
    ]
    s = funding_shadow.score(toks)
    assert s["SHORTS"] > s["FLAT"] > s["LONGS"]


def test_funding_shadow_missing_data_is_neutral(make_token):
    toks = [
        make_token("A", funding_rate=-0.001),
        make_token("B", funding_rate=0.001),
        make_token("NODATA", funding_rate=None),
    ]
    s = funding_shadow.score(toks)
    assert s["NODATA"] == 0.0


def test_funding_shadow_zscored(make_token):
    toks = [make_token("A", funding_rate=-0.002), make_token("B", funding_rate=0.002)]
    s = funding_shadow.score(toks)
    assert math.isclose(s["A"] + s["B"], 0.0, abs_tol=1e-9)  # z-scores center at 0


# --- momentum ---
def test_momentum_ranks_by_return(make_token):
    toks = [
        make_token("UP", return_24h=0.20),
        make_token("MID", return_24h=0.00),
        make_token("DOWN", return_24h=-0.20),
    ]
    s = momentum.score(toks)
    assert s["UP"] > s["MID"] > s["DOWN"]


# --- blend + select ---
def test_blend_weights_funding_vs_momentum():
    funding = {"A": 1.0, "B": -1.0}
    mom = {"A": -1.0, "B": 1.0}
    pure_funding = blend(funding, mom, funding_weight=1.0)
    assert pure_funding["A"] == 1.0 and pure_funding["B"] == -1.0
    half = blend(funding, mom, funding_weight=0.5)
    assert half["A"] == 0.0 and half["B"] == 0.0


def test_select_basket_takes_top_positive_only():
    blended = {"A": 2.0, "B": 1.0, "C": 0.5, "D": -0.5}
    assert select_basket(blended, n=2) == ["A", "B"]
    # never selects non-positive scores even if basket has room
    assert select_basket(blended, n=10) == ["A", "B", "C"]


# --- Fear & Greed throttle (contrarian) ---
def test_fear_greed_contrarian_bounds():
    assert exposure(0, 0.4, 1.0) == 1.0     # extreme fear -> max exposure
    assert exposure(100, 0.4, 1.0) == 0.4   # extreme greed -> min exposure
    assert math.isclose(exposure(50, 0.4, 1.0), 0.7)  # neutral -> midpoint


def test_fear_greed_clamps_out_of_range():
    assert exposure(-20, 0.4, 1.0) == 1.0
    assert exposure(140, 0.4, 1.0) == 0.4
