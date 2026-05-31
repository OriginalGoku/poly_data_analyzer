"""Tests for the TP x SL bracket first-passage EV grid."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nba_tipoff_bracket import _band_grids, _bracket_pnl, _grid_from_paths


def test_bracket_take_profit_hit_first():
    # Rises to TP (0.95) before falling to SL (0.40); TP=0.90, SL=0.50.
    prices = np.array([0.80, 0.95, 0.40])
    pnl, kind = _bracket_pnl(0.80, prices, won=True, stop=0.50, target=0.90, fee=0.0, slippage=0.0)
    assert kind == "take_profit"
    assert pnl == pytest.approx(0.90 - 0.80)


def test_bracket_stop_loss_hit_first():
    # Falls to SL (0.45) before rising to TP (0.95).
    prices = np.array([0.80, 0.45, 0.95])
    pnl, kind = _bracket_pnl(0.80, prices, won=True, stop=0.50, target=0.90, fee=0.0, slippage=0.0)
    assert kind == "stop_loss"
    assert pnl == pytest.approx(0.50 - 0.80)


def test_bracket_stop_loss_applies_slippage():
    prices = np.array([0.80, 0.45])
    pnl, kind = _bracket_pnl(0.80, prices, won=False, stop=0.50, target=0.90, fee=0.0, slippage=0.02)
    assert kind == "stop_loss"
    assert pnl == pytest.approx((0.50 - 0.02) - 0.80)  # market-order slippage


def test_bracket_take_profit_no_slippage():
    prices = np.array([0.80, 0.95])
    pnl, kind = _bracket_pnl(0.80, prices, won=True, stop=0.50, target=0.90, fee=0.0, slippage=0.02)
    assert kind == "take_profit"
    assert pnl == pytest.approx(0.90 - 0.80)  # limit sell, slippage ignored


def test_bracket_settles_when_neither_barrier_touched():
    prices = np.array([0.80, 0.82, 0.78])
    win_pnl, win_kind = _bracket_pnl(0.80, prices, won=True, stop=0.50, target=0.95, fee=0.0, slippage=0.0)
    loss_pnl, loss_kind = _bracket_pnl(0.80, prices, won=False, stop=0.50, target=0.95, fee=0.0, slippage=0.0)
    assert win_kind == "settle" and loss_kind == "settle"
    assert win_pnl == pytest.approx(1.0 - 0.80)
    assert loss_pnl == pytest.approx(0.0 - 0.80)


def test_bracket_empty_path_settles():
    pnl, kind = _bracket_pnl(0.80, np.array([]), won=True, stop=0.50, target=0.95, fee=0.0, slippage=0.0)
    assert kind == "settle"
    assert pnl == pytest.approx(0.20)


def test_bracket_fee_applied_to_every_outcome():
    prices = np.array([0.80, 0.95])
    pnl, _ = _bracket_pnl(0.80, prices, won=True, stop=0.50, target=0.90, fee=0.01, slippage=0.0)
    assert pnl == pytest.approx(0.90 - 0.80 - 0.01)


def test_underdog_take_profit_salvages_losing_spike():
    # Favorite entry 0.80 -> underdog entry 0.20. BOTH favorites win (underdogs
    # lose), but game A's underdog spikes to 0.70 mid-game before collapsing.
    paths = [
        # fav path [0.80,0.30,0.95] -> underdog [0.20,0.70,0.05]: spikes then dies
        ("Lower Strong", True, 0.80, np.array([0.80, 0.30, 0.95])),
        # fav path [0.80,0.95] -> underdog [0.20,0.05]: never spikes
        ("Lower Strong", True, 0.80, np.array([0.80, 0.95])),
    ]
    grid = _grid_from_paths(paths, side="underdog", fee=0.0, slippage=0.0, stop_step=0.02, target_step=0.02)
    assert not grid.empty
    assert grid["entry_price_used"].iloc[0] == pytest.approx(0.20)
    # Both underdogs lose -> hold-to-settlement EV = -entry = -0.20.
    assert grid["ev_no_bracket_reference"].iloc[0] == pytest.approx(-0.20)
    # Cell (stop=0, target=0.50): game A TP at 0.50 (+0.30); game B settles 0 (-0.20).
    cell = grid[(grid["stop_price"] == 0.0) & (grid["target_price"].round(4) == 0.50)].iloc[0]
    assert cell["ev_per_unit_stake"] == pytest.approx((0.30 - 0.20) / 2)  # +0.05 > -0.20
    assert cell["ev_per_unit_stake"] > grid["ev_no_bracket_reference"].iloc[0]


def test_favorite_and_underdog_grids_differ():
    paths = [
        ("Lower Strong", True, 0.80, np.array([0.80, 0.95])),
        ("Lower Strong", False, 0.80, np.array([0.80, 0.30])),
    ]
    fav = _grid_from_paths(paths, "favorite", 0.0, 0.0, 0.02, 0.02)
    dog = _grid_from_paths(paths, "underdog", 0.0, 0.0, 0.02, 0.02)
    assert fav["entry_price_used"].iloc[0] == pytest.approx(0.80)
    assert dog["entry_price_used"].iloc[0] == pytest.approx(0.20)


def test_band_grids_bracket_entry_bounds():
    stops, targets = _band_grids(0.80, stop_step=0.02, target_step=0.02)
    assert stops[0] == 0.0
    assert all(s < 0.80 for s in stops)
    assert all(t > 0.80 for t in targets)
    assert targets[-1] == 1.0  # no-take-profit reference
