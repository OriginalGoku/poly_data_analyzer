"""Tests for backtest grid runner."""
from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from backtest.backtest_config import DipBuyBacktestConfig
from backtest.backtest_runner import run_backtest_grid


@pytest.fixture
def mock_universe():
    """Mock universe of Upper Strong games."""
    return [
        ("2026-03-23", "nba_game_1", "nba", 0.92, 0.91, 1, True, "good"),
        ("2026-03-24", "nba_game_2", "nba", 0.88, 0.87, 2, True, "good"),
    ]


def test_run_backtest_grid_empty_universe():
    """Test backtest grid with empty universe."""
    config = DipBuyBacktestConfig(dip_thresholds=(10,))

    with patch("backtest.backtest_runner.filter_upper_strong_universe") as mock_universe:
        mock_universe.return_value = []

        agg_df, per_game_df = run_backtest_grid(
            start_date=datetime(2026, 3, 23),
            end_date=datetime(2026, 3, 30),
            configs=[config],
        )

    assert len(agg_df) == 0
    assert len(per_game_df) == 0


def test_run_backtest_grid_basic(mock_universe):
    """Test basic backtest grid execution."""
    config = DipBuyBacktestConfig(dip_thresholds=(10, 15))

    mock_result = {
        "strategy": "dip_buy",
        "dip_threshold": 10,
        "exit_type": "settlement",
        "fee_model": "taker",
        "sport": "nba",
        "match_id": "nba_game_1",
        "date": "2026-03-23",
        "entry_price": 0.81,
        "exit_price": 0.87,
        "gross_pnl_cents": 6.0,
        "net_pnl_cents": 5.8,
        "roi_pct": 0.07,
        "hold_seconds": 300,
        "settlement_method": "event_derived",
        "settlement_occurred": True,
        "true_pnl_cents": 11.0,
        "baseline_buy_at_open_roi": 0.05,
        "baseline_buy_at_tip_roi": 0.04,
        "baseline_buy_first_ingame_roi": 0.06,
        "status": "filled",
    }

    with patch("backtest.backtest_runner.filter_upper_strong_universe") as mock_univ, \
         patch("backtest.backtest_runner.backtest_single_game") as mock_backtest:
        mock_univ.return_value = mock_universe
        mock_backtest.return_value = mock_result

        agg_df, per_game_df = run_backtest_grid(
            start_date=datetime(2026, 3, 23),
            end_date=datetime(2026, 3, 30),
            configs=[config],
        )

    assert len(per_game_df) > 0
    assert "dip_threshold" in per_game_df.columns
    assert "roi_pct" in per_game_df.columns
    assert len(agg_df) > 0


def test_run_backtest_grid_sport_filter(mock_universe):
    """Test sport filter in grid."""
    config = DipBuyBacktestConfig(sport_filter="mlb")

    with patch("backtest.backtest_runner.filter_upper_strong_universe") as mock_univ:
        mock_univ.return_value = mock_universe  # All NBA games

        agg_df, per_game_df = run_backtest_grid(
            start_date=datetime(2026, 3, 23),
            end_date=datetime(2026, 3, 30),
            configs=[config],
        )

    # Should skip all NBA games due to filter
    assert len(per_game_df) == 0


def test_run_backtest_grid_multiple_configs(mock_universe):
    """Test grid with multiple configs."""
    config1 = DipBuyBacktestConfig(dip_thresholds=(10,), fee_model="taker")
    config2 = DipBuyBacktestConfig(dip_thresholds=(15,), fee_model="maker")

    mock_result = {
        "strategy": "dip_buy",
        "dip_threshold": 10,
        "dip_anchor": "open",
        "exit_type": "settlement",
        "fee_model": "taker",
        "sport": "nba",
        "match_id": "nba_game_1",
        "date": "2026-03-23",
        "entry_price": 0.81,
        "exit_price": 0.87,
        "gross_pnl_cents": 6.0,
        "net_pnl_cents": 5.676,
        "roi_pct": 0.07,
        "hold_seconds": 300,
        "settlement_method": "event_derived",
        "settlement_occurred": True,
        "true_pnl_cents": 11.0,
        "baseline_buy_at_open_roi": 0.05,
        "baseline_buy_at_tip_roi": 0.04,
        "baseline_buy_first_ingame_roi": 0.06,
        "status": "filled",
    }

    with patch("backtest.backtest_runner.filter_upper_strong_universe") as mock_univ, \
         patch("backtest.backtest_runner.backtest_single_game") as mock_backtest:
        mock_univ.return_value = mock_universe
        mock_backtest.return_value = mock_result

        agg_df, per_game_df = run_backtest_grid(
            start_date=datetime(2026, 3, 23),
            end_date=datetime(2026, 3, 30),
            configs=[config1, config2],
        )

    # Should call backtest for each config × universe combo
    assert mock_backtest.call_count >= 2

    # gross_roi_mean is derived from gross_pnl_cents; net_roi_mean from roi_pct
    # With fee_pct > 0, they must differ
    taker_rows = agg_df[agg_df["fee_model"] == "taker"]
    if len(taker_rows) > 0:
        assert (taker_rows["gross_roi_mean"] != taker_rows["net_roi_mean"]).any()
        assert (taker_rows["gross_roi_mean"] > taker_rows["net_roi_mean"]).all()


def test_run_backtest_grid_gross_roi_mean_formula(mock_universe):
    """gross_roi_mean uses gross_pnl_cents / (entry_price * 100), not roi_pct."""
    config = DipBuyBacktestConfig(dip_thresholds=(10,), fee_model="taker")

    # entry=0.80, exit=0.85 → gross=5c, fee≈0.33c, net≈4.67c
    mock_result = {
        "strategy": "dip_buy",
        "dip_threshold": 10,
        "dip_anchor": "open",
        "exit_type": "settlement",
        "fee_model": "taker",
        "sport": "nba",
        "match_id": "nba_game_1",
        "date": "2026-03-23",
        "entry_price": 0.80,
        "exit_price": 0.85,
        "gross_pnl_cents": 5.0,
        "net_pnl_cents": 4.67,
        "roi_pct": 0.0584,  # 4.67 / 80 ≈ 5.84%
        "hold_seconds": 600,
        "settlement_method": "event_derived",
        "settlement_occurred": True,
        "true_pnl_cents": 20.0,
        "baseline_buy_at_open_roi": 0.03,
        "baseline_buy_at_tip_roi": 0.02,
        "baseline_buy_first_ingame_roi": 0.04,
        "status": "filled",
    }

    with patch("backtest.backtest_runner.filter_upper_strong_universe") as mock_univ, \
         patch("backtest.backtest_runner.backtest_single_game") as mock_backtest:
        mock_univ.return_value = [mock_universe[0]]  # Single game
        mock_backtest.return_value = mock_result

        agg_df, _ = run_backtest_grid(
            start_date=datetime(2026, 3, 23),
            end_date=datetime(2026, 3, 23),
            configs=[config],
        )

    assert len(agg_df) == 1
    row = agg_df.iloc[0]
    # gross_roi_mean = gross_pnl_cents / (entry_price * 100) = 5.0 / 80 = 0.0625
    assert abs(row["gross_roi_mean"] - (5.0 / (0.80 * 100))) < 0.0001
    # net_roi_mean comes from roi_pct directly
    assert abs(row["net_roi_mean"] - 0.0584) < 0.0001
    # Gross must be larger than net (fees deducted)
    assert row["gross_roi_mean"] > row["net_roi_mean"]


def test_run_backtest_grid_dip_anchor_propagated(mock_universe):
    """dip_anchor from config is preserved in per_game_df and used for aggregation."""
    config = DipBuyBacktestConfig(dip_thresholds=(10,), dip_anchor="tipoff")

    mock_result = {
        "strategy": "dip_buy",
        "dip_threshold": 10,
        "dip_anchor": "tipoff",
        "exit_type": "settlement",
        "fee_model": "taker",
        "sport": "nba",
        "match_id": "nba_game_1",
        "date": "2026-03-23",
        "entry_price": 0.80,
        "exit_price": 0.85,
        "gross_pnl_cents": 5.0,
        "net_pnl_cents": 4.67,
        "roi_pct": 0.058,
        "hold_seconds": 600,
        "settlement_method": "event_derived",
        "settlement_occurred": True,
        "true_pnl_cents": 20.0,
        "baseline_buy_at_open_roi": 0.03,
        "baseline_buy_at_tip_roi": 0.02,
        "baseline_buy_first_ingame_roi": 0.04,
        "status": "filled",
    }

    with patch("backtest.backtest_runner.filter_upper_strong_universe") as mock_univ, \
         patch("backtest.backtest_runner.backtest_single_game") as mock_backtest:
        mock_univ.return_value = [mock_universe[0]]
        mock_backtest.return_value = mock_result

        agg_df, per_game_df = run_backtest_grid(
            start_date=datetime(2026, 3, 23),
            end_date=datetime(2026, 3, 23),
            configs=[config],
        )

    assert "dip_anchor" in per_game_df.columns
    assert per_game_df.iloc[0]["dip_anchor"] == "tipoff"
    assert len(agg_df) == 1
    assert agg_df.iloc[0]["dip_anchor"] == "tipoff"
