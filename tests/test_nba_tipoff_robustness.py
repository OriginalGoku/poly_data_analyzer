"""Tests for walk-forward + bootstrap robustness checks."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nba_tipoff_robustness import (
    BOOTSTRAP_COLUMNS,
    WALK_FORWARD_COLUMNS,
    _per_game_stop_pnl,
    bootstrap_stop_loss_ci,
    walk_forward_stop_loss,
)
from settings import ChartSettings


def test_per_game_pnl_stop_eligibility_and_settle():
    mins = np.array([0.30, 0.30, 0.90])
    wons = np.array([False, True, True])
    entries = np.array([0.50, 0.50, 0.40])
    # stop 0.40: eligible where 0.40 < entry -> games 0,1 (entry .50); game2 entry .40 not eligible.
    pnl = _per_game_stop_pnl(mins, wons, entries, stop=0.40, fee=0.0, slippage=0.0)
    # game0 loss, stopped at 0.40 -> 0.40-0.50 = -0.10
    assert pnl[0] == pytest.approx(-0.10)
    # game1 win but min 0.30 <= 0.40 and eligible -> stopped at 0.40 -> -0.10
    assert pnl[1] == pytest.approx(-0.10)
    # game2 not eligible (stop>=entry) -> settle win -> 1-0.40 = 0.60
    assert pnl[2] == pytest.approx(0.60)


def test_per_game_pnl_no_stop_settles_all():
    mins = np.array([0.30, 0.90])
    wons = np.array([False, True])
    entries = np.array([0.50, 0.50])
    pnl = _per_game_stop_pnl(mins, wons, entries, stop=0.0, fee=0.0, slippage=0.0)
    assert pnl[0] == pytest.approx(-0.50)  # loss settles 0
    assert pnl[1] == pytest.approx(0.50)   # win settles 1


def _synthetic_dataset(n=40):
    # Two bands; losers dip to 0.30, winners hold high. 60% win.
    rng = np.random.default_rng(1)
    rows = []
    for i in range(n):
        won = i % 5 != 0  # 80% win
        band = "Lower Strong" if i % 2 == 0 else "Upper Strong"
        rows.append(
            {
                "date": f"2024-01-{(i % 28) + 1:02d}",
                "match_id": f"m{i}",
                "tipoff_interpretable_band": band,
                "tipoff_favorite_won": won,
                "tipoff_favorite_avg_last_n_pretip_price": 0.80,
                "tipoff_favorite_in_game_min_price": 0.85 if won else 0.30,
            }
        )
    return pd.DataFrame(rows)


def test_walk_forward_shape_and_folds():
    df = _synthetic_dataset(50)
    wf = walk_forward_stop_loss(df, ChartSettings(), n_folds=5)
    assert list(wf.columns) == list(WALK_FORWARD_COLUMNS)
    assert not wf.empty
    assert (wf["n_folds"] >= 1).all()
    assert (wf["folds_positive"] <= wf["n_folds"]).all()


def test_walk_forward_empty_without_dates():
    df = _synthetic_dataset(20).drop(columns=["date"])
    assert walk_forward_stop_loss(df, ChartSettings()).empty


def test_bootstrap_ci_shape_and_bounds():
    df = _synthetic_dataset(60)
    boot = bootstrap_stop_loss_ci(df, ChartSettings(), n_boot=500, seed=7)
    assert list(boot.columns) == list(BOOTSTRAP_COLUMNS)
    assert not boot.empty
    for _, r in boot.iterrows():
        assert r["ev_ci_low"] <= r["ev_per_unit_stake"] <= r["ev_ci_high"]
        assert 0.0 <= r["prob_ev_positive"] <= 1.0


def test_bootstrap_deterministic_with_seed():
    df = _synthetic_dataset(60)
    a = bootstrap_stop_loss_ci(df, ChartSettings(), n_boot=300, seed=42)
    b = bootstrap_stop_loss_ci(df, ChartSettings(), n_boot=300, seed=42)
    pd.testing.assert_frame_equal(a, b)
