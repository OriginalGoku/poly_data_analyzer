"""Tests for single-game backtest execution."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backtest_config import DipBuyBacktestConfig
from backtest_single_game import backtest_single_game


@pytest.fixture
def mock_game_data():
    """Create mock game data."""
    base_time = datetime(2026, 3, 23, 19, 30, 0)

    trades_df = pd.DataFrame(
        {
            "time": [
                base_time + timedelta(minutes=1),
                base_time + timedelta(minutes=2),
                base_time + timedelta(minutes=3),
                base_time + timedelta(minutes=5),
                base_time + timedelta(minutes=10),
            ],
            "price": [0.92, 0.91, 0.81, 0.84, 0.87],
        }
    )

    events = pd.DataFrame(
        [
            {
                "time": "2026-03-23T20:30:00",
                "period": 4,
                "away_score": 105,
                "home_score": 102,
            },
        ]
    )

    manifest = {
        "match_id": "nba_game_1",
        "sport": "nba",
        "open_favorite_token": 0,
        "gamma_start_time": base_time.isoformat(),
        "game_close_time": (base_time + timedelta(hours=2, minutes=30)).isoformat(),
    }

    return {
        "trades": trades_df,
        "events": events,
        "manifest": manifest,
    }


@pytest.fixture
def mock_analytics_view():
    """Create mock analytics view."""
    return pd.DataFrame(
        [
            {
                "match_id": "nba_game_1",
                "date": "2026-03-23",
                "sport": "nba",
                "open_favorite_price": 0.92,
                "tipoff_favorite_price": 0.91,
                "open_favorite_team": "LAL",
                "has_events": True,
                "has_final_score": True,
                "price_quality": "good",
            },
        ]
    )


def test_backtest_single_game_basic(mock_game_data, mock_analytics_view):
    """Test basic single-game backtest."""
    config = DipBuyBacktestConfig(dip_thresholds=(10,), exit_type="settlement")

    with patch("backtest_single_game.load_game") as mock_load_game, \
         patch("backtest_single_game.get_analytics_view") as mock_analytics:
        mock_load_game.return_value = mock_game_data
        mock_analytics.return_value = mock_analytics_view

        result = backtest_single_game(
            date="2026-03-23",
            match_id="nba_game_1",
            config=config,
        )

    assert result is not None
    assert result["match_id"] == "nba_game_1"
    assert result["date"] == "2026-03-23"
    assert result["sport"] == "nba"
    assert result["status"] in ["filled", "not_triggered"]
    assert "roi_pct" in result
    assert "baseline_buy_at_open_roi" in result


def test_backtest_single_game_no_dip_triggered(mock_game_data, mock_analytics_view):
    """Test game where dip threshold is never triggered."""
    config = DipBuyBacktestConfig(dip_thresholds=(50,), exit_type="settlement")

    with patch("backtest_single_game.load_game") as mock_load_game, \
         patch("backtest_single_game.get_analytics_view") as mock_analytics:
        mock_load_game.return_value = mock_game_data
        mock_analytics.return_value = mock_analytics_view

        result = backtest_single_game(
            date="2026-03-23",
            match_id="nba_game_1",
            config=config,
        )

    assert result is not None
    assert result["status"] == "not_triggered"
    assert result["entry_price"] is None
    assert result["roi_pct"] == 0


def test_backtest_single_game_load_failure(mock_analytics_view):
    """Test game where loading fails."""
    config = DipBuyBacktestConfig()

    with patch("backtest_single_game.load_game") as mock_load_game:
        mock_load_game.side_effect = Exception("Load error")

        result = backtest_single_game(
            date="2026-03-23",
            match_id="nba_game_1",
            config=config,
        )

    assert result is not None
    assert result["status"] == "failed_to_load"
    assert "error" in result


def test_backtest_single_game_missing_analytics(mock_game_data):
    """Test game where analytics are missing."""
    config = DipBuyBacktestConfig()

    empty_analytics = pd.DataFrame({"match_id": [], "date": []})

    with patch("backtest_single_game.load_game") as mock_load_game, \
         patch("backtest_single_game.get_analytics_view") as mock_analytics:
        mock_load_game.return_value = mock_game_data
        mock_analytics.return_value = empty_analytics

        result = backtest_single_game(
            date="2026-03-23",
            match_id="nba_game_1",
            config=config,
        )

    assert result is not None
    assert result["status"] == "missing_analytics"


def test_backtest_single_game_different_exit_types(mock_game_data, mock_analytics_view):
    """Test different exit types on same game."""
    for exit_type in ["settlement", "reversion_to_open"]:
        config = DipBuyBacktestConfig(
            dip_thresholds=(10,), exit_type=exit_type
        )

        with patch("backtest_single_game.load_game") as mock_load_game, \
             patch("backtest_single_game.get_analytics_view") as mock_analytics:
            mock_load_game.return_value = mock_game_data
            mock_analytics.return_value = mock_analytics_view

            result = backtest_single_game(
                date="2026-03-23",
                match_id="nba_game_1",
                config=config,
            )

        assert result is not None
        assert result["exit_type"] == exit_type


def test_backtest_single_game_fee_models(mock_game_data, mock_analytics_view):
    """Test different fee models."""
    for fee_model in ["taker", "maker"]:
        config = DipBuyBacktestConfig(fee_model=fee_model)

        with patch("backtest_single_game.load_game") as mock_load_game, \
             patch("backtest_single_game.get_analytics_view") as mock_analytics:
            mock_load_game.return_value = mock_game_data
            mock_analytics.return_value = mock_analytics_view

            result = backtest_single_game(
                date="2026-03-23",
                match_id="nba_game_1",
                config=config,
            )

        assert result is not None
        assert result["fee_model"] == fee_model


def test_backtest_includes_baselines(mock_game_data, mock_analytics_view):
    """Test that baselines are included in results."""
    config = DipBuyBacktestConfig()

    with patch("backtest_single_game.load_game") as mock_load_game, \
         patch("backtest_single_game.get_analytics_view") as mock_analytics:
        mock_load_game.return_value = mock_game_data
        mock_analytics.return_value = mock_analytics_view

        result = backtest_single_game(
            date="2026-03-23",
            match_id="nba_game_1",
            config=config,
        )

    assert "baseline_buy_at_open_roi" in result
    assert "baseline_buy_at_tip_roi" in result
    assert "baseline_buy_first_ingame_roi" in result
