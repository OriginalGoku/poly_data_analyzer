"""Unit tests for band_drop_recovery aggregator."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import pandas as pd
import pytest

from band_drop_recovery import (
    SWEEP_DROP_COL,
    compute_band_totals,
    compute_recovery_grid,
    partition_games,
)
from nba_analysis import _wilson_interval


ACTIVE_BANDS = (
    "Lean Favorite",
    "Lower Moderate",
    "Upper Moderate",
    "Lower Strong",
    "Upper Strong",
)
DROPS = (10, 20, 30, 40, 50)


def _pos_row(
    date: str,
    match_id: str,
    drop_pct: float,
    exit_kind: str,
    entry_price: float = 0.90,
    entry_time: datetime | None = None,
    exit_time: datetime | None = None,
    max_drawdown_cents: float = 0.0,
) -> dict:
    et = entry_time or datetime(2026, 1, 1, 19, 5)
    xt = exit_time or (et + timedelta(minutes=10))
    return {
        "date": date,
        "match_id": match_id,
        "entry_price": entry_price,
        "exit_price": entry_price * 1.05,
        "entry_time": et,
        "exit_time": xt,
        "exit_kind": exit_kind,
        "max_drawdown_cents": max_drawdown_cents,
        SWEEP_DROP_COL: float(drop_pct),
        "pnl": 1.0,
        "roi_pct": 5.0,
    }


def _base(date: str, match_id: str, band: str, tipoff_price: float = 0.90) -> dict:
    return {
        "date": date,
        "match_id": match_id,
        "open_interpretable_band": band,
        "tipoff_favorite_price": tipoff_price,
        "open_favorite_price": tipoff_price,
        "sport": "nba",
        "price_quality": "live",
    }


def test_empty_positions_returns_shaped_grid():
    out = compute_recovery_grid(
        pd.DataFrame(),
        pd.DataFrame([_base("2026-01-01", "m1", "Upper Strong")]),
        ACTIVE_BANDS,
        DROPS,
    )
    assert list(out["grid"].index) == list(ACTIVE_BANDS)
    assert [float(c) for c in out["grid"].columns] == [float(d) for d in DROPS]
    assert out["detail"].empty


def test_upper_strong_recover_at_10_20_30_not_40():
    positions = pd.DataFrame(
        [
            _pos_row("2026-01-01", "m1", 10, "reversion"),
            _pos_row("2026-01-01", "m1", 20, "reversion"),
            _pos_row("2026-01-01", "m1", 30, "reversion"),
            _pos_row("2026-01-01", "m1", 40, "forced_close"),
        ]
    )
    base = pd.DataFrame([_base("2026-01-01", "m1", "Upper Strong")])
    out = compute_recovery_grid(positions, base, ACTIVE_BANDS, DROPS, min_n_display=5)
    grid = out["grid"]
    for d in (10, 20, 30):
        cell = grid.at["Upper Strong", float(d)]
        assert cell["n"] == 1
        assert cell["rate"] == 1.0
        assert cell["low_n"] is True  # n < min_n_display
    cell40 = grid.at["Upper Strong", 40.0]
    assert cell40["n"] == 1
    assert cell40["rate"] == 0.0
    cell50 = grid.at["Upper Strong", 50.0]
    assert cell50["n"] == 0
    assert cell50["rate"] is None


def test_two_games_50pct_wilson_matches_helper():
    positions = pd.DataFrame(
        [
            _pos_row("2026-01-01", "g1", 20, "reversion"),
            _pos_row("2026-01-02", "g2", 20, "forced_close"),
        ]
    )
    base = pd.DataFrame(
        [
            _base("2026-01-01", "g1", "Lower Moderate"),
            _base("2026-01-02", "g2", "Lower Moderate"),
        ]
    )
    out = compute_recovery_grid(positions, base, ACTIVE_BANDS, DROPS)
    cell = out["grid"].at["Lower Moderate", 20.0]
    assert cell["n"] == 2
    assert cell["rate"] == 0.5
    detail = out["detail"]
    row = detail[(detail["band"] == "Lower Moderate") & (detail["drop_pct"] == 20.0)].iloc[0]
    expected_lo, expected_hi = _wilson_interval(0.5, 2)
    assert row["wilson_lo"] == pytest.approx(expected_lo)
    assert row["wilson_hi"] == pytest.approx(expected_hi)


def test_no_pnl_or_roi_columns_in_output():
    positions = pd.DataFrame([_pos_row("2026-01-01", "m1", 10, "reversion")])
    base = pd.DataFrame([_base("2026-01-01", "m1", "Upper Strong")])
    out = compute_recovery_grid(positions, base, ACTIVE_BANDS, DROPS)
    for col in out["detail"].columns:
        assert "pnl" not in col.lower()
        assert "roi" not in col.lower()


def test_toss_up_defensively_dropped():
    positions = pd.DataFrame([_pos_row("2026-01-01", "tu", 10, "reversion")])
    base = pd.DataFrame([_base("2026-01-01", "tu", "Toss-Up")])
    out = compute_recovery_grid(positions, base, ACTIVE_BANDS, DROPS)
    for d in DROPS:
        for b in ACTIVE_BANDS:
            assert out["grid"].at[b, float(d)]["n"] == 0


def test_cumulative_invariant_shallow_n_geq_deeper_n():
    positions = pd.DataFrame(
        [
            _pos_row("2026-01-01", f"g{i}", drop, "reversion" if i % 2 else "forced_close")
            for i in range(8)
            for drop in (10, 30, 50)
            if (drop, i) != (50, 0) and (drop, i) != (50, 1)  # fewer 50% triggers
        ]
    )
    base = pd.DataFrame(
        [_base("2026-01-01", f"g{i}", "Upper Strong") for i in range(8)]
    )
    out = compute_recovery_grid(positions, base, ACTIVE_BANDS, DROPS)
    n10 = out["grid"].at["Upper Strong", 10.0]["n"]
    n30 = out["grid"].at["Upper Strong", 30.0]["n"]
    n50 = out["grid"].at["Upper Strong", 50.0]["n"]
    assert n10 >= n30 >= n50


def test_further_drawdown_pct_from_max_drawdown_cents():
    # entry_price 0.80, max_drawdown_cents 16 -> min_price = 0.64, further = 0.20
    positions = pd.DataFrame(
        [
            _pos_row(
                "2026-01-01", "m1", 10, "reversion",
                entry_price=0.80, max_drawdown_cents=16.0,
            )
        ]
    )
    base = pd.DataFrame([_base("2026-01-01", "m1", "Upper Strong")])
    out = compute_recovery_grid(positions, base, ACTIVE_BANDS, DROPS)
    detail = out["detail"]
    row = detail[(detail["band"] == "Upper Strong") & (detail["drop_pct"] == 10.0)].iloc[0]
    assert row["median_further_drawdown_pct"] == pytest.approx(0.20)


def test_negative_drawdown_clamped():
    positions = pd.DataFrame(
        [
            _pos_row(
                "2026-01-01", "m1", 10, "reversion",
                entry_price=0.80, max_drawdown_cents=-5.0,
            )
        ]
    )
    base = pd.DataFrame([_base("2026-01-01", "m1", "Upper Strong")])
    out = compute_recovery_grid(positions, base, ACTIVE_BANDS, DROPS)
    detail = out["detail"]
    row = detail[(detail["band"] == "Upper Strong") & (detail["drop_pct"] == 10.0)].iloc[0]
    assert row["median_further_drawdown_pct"] == pytest.approx(0.0)


def test_missing_sweep_column_raises():
    positions = pd.DataFrame([{"date": "2026-01-01", "match_id": "m", "exit_kind": "reversion"}])
    base = pd.DataFrame([_base("2026-01-01", "m", "Upper Strong")])
    with pytest.raises(ValueError, match="sweep"):
        compute_recovery_grid(positions, base, ACTIVE_BANDS, DROPS)


def test_partition_games_filters_and_excludes_missing_tipoff():
    base = pd.DataFrame(
        [
            _base("2026-01-01", "a", "Upper Strong", tipoff_price=0.90),
            _base("2026-01-02", "b", "Lower Strong", tipoff_price=0.80),
            {**_base("2026-01-03", "c", "Upper Moderate"), "tipoff_favorite_price": None},
        ]
    )
    out = partition_games(base, {"sport": "nba"})
    assert out["total"] == 3
    assert out["excluded_missing_tipoff"] == 1
    assert ("2026-01-01", "a") in out["kept_match_ids"]
    assert ("2026-01-03", "c") not in out["kept_match_ids"]


def test_partition_games_min_price_filter():
    base = pd.DataFrame(
        [
            _base("2026-01-01", "a", "Upper Strong", tipoff_price=0.90),
            _base("2026-01-02", "b", "Lean Favorite", tipoff_price=0.52),
        ]
    )
    out = partition_games(base, {"sport": "nba", "min_open_favorite_price": 0.60})
    assert out["total"] == 1
    assert ("2026-01-01", "a") in out["kept_match_ids"]


def test_compute_band_totals_excludes_missing_tipoff():
    base = pd.DataFrame(
        [
            _base("2026-01-01", "a", "Upper Strong"),
            _base("2026-01-02", "b", "Upper Strong"),
            {**_base("2026-01-03", "c", "Upper Strong"), "tipoff_favorite_price": math.nan},
        ]
    )
    totals = compute_band_totals(base)
    upper = totals[totals["band"] == "Upper Strong"].iloc[0]
    assert upper["n"] == 2
