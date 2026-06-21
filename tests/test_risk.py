"""Risk sizing: inverse-vol weights, per-token cap with redistribution, gross scaling.

This is the product. Every invariant the overlay promises is pinned here.
"""

from __future__ import annotations

import math

import pytest

from ballast.risk import inverse_vol_weights


def total(w):
    return sum(w.values())


def test_inverse_vol_lower_vol_gets_more_weight():
    w = inverse_vol_weights({"LO": 0.2, "HI": 0.8}, gross=1.0, cap=1.0)
    assert w["LO"] > w["HI"]
    # weights inversely proportional to vol: 1/0.2 : 1/0.8 == 4:1
    assert math.isclose(w["LO"] / w["HI"], 4.0, rel_tol=1e-6)


def test_weights_scale_to_gross_exposure():
    w = inverse_vol_weights({"A": 0.5, "B": 0.5}, gross=0.6, cap=1.0)
    assert math.isclose(total(w), 0.6, rel_tol=1e-9)


def test_per_token_cap_enforced():
    w = inverse_vol_weights({"A": 0.1, "B": 1.0, "C": 1.0}, gross=1.0, cap=0.2)
    assert all(v <= 0.2 + 1e-9 for v in w.values())


def test_cap_excess_redistributed_to_uncapped():
    # A would dominate (tiny vol) but is capped; excess flows to B and C.
    w = inverse_vol_weights({"A": 0.01, "B": 0.5, "C": 0.5}, gross=1.0, cap=0.4)
    assert math.isclose(w["A"], 0.4, rel_tol=1e-6)
    assert math.isclose(total(w), 1.0, rel_tol=1e-6)
    assert math.isclose(w["B"], w["C"], rel_tol=1e-6)


def test_all_capped_leaves_residual_in_stable():
    # gross 1.0, cap 0.2, only 3 names -> max deployable 0.6, rest stays stable.
    w = inverse_vol_weights({"A": 0.3, "B": 0.3, "C": 0.3}, gross=1.0, cap=0.2)
    assert math.isclose(total(w), 0.6, rel_tol=1e-6)
    assert all(math.isclose(v, 0.2, rel_tol=1e-6) for v in w.values())


def test_empty_basket_is_empty():
    assert inverse_vol_weights({}, gross=1.0, cap=0.2) == {}


def test_zero_or_negative_vol_rejected():
    with pytest.raises(ValueError):
        inverse_vol_weights({"A": 0.0}, gross=1.0, cap=0.2)
