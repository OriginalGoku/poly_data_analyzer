"""Tests for backtest grid runner."""
from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from backtest_config import DipBuyBacktestConfig
from backtest_runner import run_backtest_grid


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

    with patch("backtest_runner.filter_upper_strong_universe") as mock_universe:
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

    with patch("backtest_runner.filter_upper_strong_universe") as mock_univ, \
         patch("backtest_runner.backtest_single_game") as mock_backtest:
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

    with patch("backtest_runner.filter_upper_strong_universe") as mock_univ:
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
        "exit_type": "settlement",
        "fee_model": "taker",
        "sport": "nba",
        "match_id": "nba_game_1",
        "date": "2026-03-23",
        "entry_price": 0.81,
        "exit_price": 0.87,
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

    with patch("backtest_runner.filter_upper_strong_universe") as mock_univ, \
         patch("backtest_runner.backtest_single_game") as mock_backtest:
        mock_univ.return_value = mock_universe
        mock_backtest.return_value = mock_result

        agg_df, per_game_df = run_backtest_grid(
            start_date=datetime(2026, 3, 23),
            end_date=datetime(2026, 3, 30),
            configs=[config1, config2],
        )

    # Should call backtest for each config × universe combo
    assert mock_backtest.call_count >= 2
