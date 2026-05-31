"""Tests for the bracket OOS + bootstrap validation."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nba_tipoff_bracket_validation import (
    BOOT_COLUMNS,
    WF_COLUMNS,
    _band_pnl_at_bracket,
    bootstrap_bracket_ci,
    walk_forward_bracket,
)


def _paths(n=40):
    # Underdog entry 0.20; alternating: half spike to 0.70 (lose), half flat (lose),
    # a quarter actually win. Dates span 40 days for fold splitting.
    out = []
    for i in range(n):
        date = f"2024-02-{(i % 28) + 1:02d}"
        won = i % 4 == 0  # 25% favorite-loss -> underdog win
        if i % 2 == 0:
            prices = np.array([0.80, 0.30, 0.95])  # underdog spikes to 0.70
        else:
            prices = np.array([0.80, 0.95])         # underdog never spikes
        out.append(("Lower Strong", date, won, 0.80, prices))
    return out


def test_band_pnl_at_bracket_underdog_side():
    paths = [
        ("Lower Strong", "2024-01-01", True, 0.80, np.array([0.80, 0.30, 0.95])),  # dog spikes, loses
    ]
    pnl, no_pnl = _band_pnl_at_bracket(paths, "underdog", {"Lower Strong": (0.0, 0.50)}, 0.0, 0.0)
    # underdog entry 0.20; TP at 0.50 hit on the 0.70 spike -> +0.30
    assert pnl["Lower Strong"][0] == pytest.approx(0.30)
    # no-bracket: underdog lost -> settle 0 -> -0.20
    assert no_pnl["Lower Strong"][0] == pytest.approx(-0.20)


def test_walk_forward_bracket_shape():
    wf = walk_forward_bracket(_paths(40), "underdog", fee=0.0, slippage=0.0, n_folds=4)
    assert list(wf.columns) == list(WF_COLUMNS)
    assert not wf.empty
    assert (wf["folds_positive"] <= wf["n_folds"]).all()
    assert (wf["side"] == "underdog").all()


def test_bootstrap_bracket_ci_bounds_and_determinism():
    a = bootstrap_bracket_ci(_paths(60), "underdog", fee=0.0, slippage=0.0, n_boot=400, seed=3)
    b = bootstrap_bracket_ci(_paths(60), "underdog", fee=0.0, slippage=0.0, n_boot=400, seed=3)
    assert list(a.columns) == list(BOOT_COLUMNS)
    assert not a.empty
    for _, r in a.iterrows():
        assert r["ev_ci_low"] <= r["ev_per_unit_stake"] <= r["ev_ci_high"]
        assert 0.0 <= r["prob_ev_positive"] <= 1.0
    pd.testing.assert_frame_equal(a, b)


def test_validation_empty_paths():
    assert walk_forward_bracket([], "underdog", 0.0, 0.0).empty
    assert bootstrap_bracket_ci([], "underdog", 0.0, 0.0).empty
