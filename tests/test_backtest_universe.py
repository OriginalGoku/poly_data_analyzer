"""Tests for backtest universe filtering."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backtest_universe import filter_upper_strong_universe


@pytest.fixture
def mock_analytics_df():
    """Create mock analytics DataFrame."""
    base_date = datetime(2026, 3, 23)
    return pd.DataFrame(
        [
            {
                "date": (base_date).isoformat(),
                "match_id": "nba_game_1",
                "sport": "nba",
                "open_favorite_price": 0.90,
                "tipoff_favorite_price": 0.89,
                "open_favorite_token_id": 1,
                "open_favorite_team": "LAL",
                "has_events": True,
                "has_final_score": True,
                "price_quality": "good",
            },
            {
                "date": (base_date + timedelta(days=1)).isoformat(),
                "match_id": "nba_game_2",
                "sport": "nba",
                "open_favorite_price": 0.80,  # Below threshold
                "tipoff_favorite_price": 0.80,
                "open_favorite_token_id": 2,
                "open_favorite_team": "BOS",
                "has_events": True,
                "has_final_score": True,
                "price_quality": "good",
            },
            {
                "date": (base_date + timedelta(days=2)).isoformat(),
                "match_id": "nba_game_3",
                "sport": "nba",
                "open_favorite_price": 0.85,  # Exactly at threshold, excluded
                "tipoff_favorite_price": 0.85,
                "open_favorite_token_id": 3,
                "open_favorite_team": "MIA",
                "has_events": True,
                "has_final_score": True,
                "price_quality": "good",
            },
            {
                "date": (base_date + timedelta(days=3)).isoformat(),
                "match_id": "nba_game_4",
                "sport": "nba",
                "open_favorite_price": 0.95,  # Upper strong
                "tipoff_favorite_price": 0.94,
                "open_favorite_token_id": 4,
                "open_favorite_team": "Tie",  # Tie, should be excluded
                "has_events": True,
                "has_final_score": True,
                "price_quality": "good",
            },
            {
                "date": (base_date + timedelta(days=4)).isoformat(),
                "match_id": "nba_game_5",
                "sport": "nba",
                "open_favorite_price": 0.92,  # Upper strong
                "tipoff_favorite_price": 0.91,
                "open_favorite_token_id": 5,
                "open_favorite_team": "GSW",
                "has_events": True,
                "has_final_score": True,
                "price_quality": "inferred",  # Inferred quality
            },
            {
                "date": (base_date + timedelta(days=5)).isoformat(),
                "match_id": "nba_game_6",
                "sport": "nba",
                "open_favorite_price": 0.88,  # Upper strong
                "tipoff_favorite_price": 0.87,
                "open_favorite_token_id": 6,
                "open_favorite_team": "DEN",
                "has_events": False,  # No events, can't settle
                "has_final_score": False,
                "price_quality": "good",
            },
        ]
    )


def test_filter_upper_strong_basic(mock_analytics_df):
    """Test basic filtering for Upper Strong favorites."""
    with patch("backtest_universe.load_game_analytics") as mock_load:
        mock_load.return_value = mock_analytics_df

        result = filter_upper_strong_universe(
            datetime(2026, 3, 23),
            datetime(2026, 3, 29),
            exclude_inferred_price_quality=False,
        )

        # Should include: game_1 (0.90), game_5 (0.92), game_6 (0.88)
        # Excluded: game_2 (0.80 <= 0.85), game_3 (0.85 <= threshold),
        #           game_4 (Tie)
        assert len(result) == 3
        assert result[0][1] == "nba_game_1"
        assert result[1][1] == "nba_game_5"
        assert result[2][1] == "nba_game_6"


def test_filter_excludes_inferred_quality(mock_analytics_df):
    """Test that inferred price_quality is excluded by default."""
    with patch("backtest_universe.load_game_analytics") as mock_load:
        mock_load.return_value = mock_analytics_df

        result = filter_upper_strong_universe(
            datetime(2026, 3, 23),
            datetime(2026, 3, 29),
            exclude_inferred_price_quality=True,
        )

        # Should include game_1, game_6 (inferred game_5 excluded)
        assert len(result) == 2
        assert result[0][1] == "nba_game_1"
        assert result[1][1] == "nba_game_6"


def test_filter_empty_date_range(mock_analytics_df):
    """Test filtering with no matching dates."""
    with patch("backtest_universe.load_game_analytics") as mock_load:
        mock_load.return_value = mock_analytics_df

        result = filter_upper_strong_universe(
            datetime(2026, 4, 1),
            datetime(2026, 4, 30),
        )

        assert len(result) == 0


def test_filter_settlement_capability(mock_analytics_df):
    """Test that settlement capability is correctly detected."""
    with patch("backtest_universe.load_game_analytics") as mock_load:
        mock_load.return_value = mock_analytics_df

        result = filter_upper_strong_universe(
            datetime(2026, 3, 23),
            datetime(2026, 3, 29),
            exclude_inferred_price_quality=False,
        )

        # game_1 should have can_settle=True
        assert result[0][6] is True  # can_settle
        # game_5 should have can_settle=True despite being inferred
        assert result[1][6] is True


def test_filter_output_schema(mock_analytics_df):
    """Test that output has correct schema."""
    with patch("backtest_universe.load_game_analytics") as mock_load:
        mock_load.return_value = mock_analytics_df

        result = filter_upper_strong_universe(
            datetime(2026, 3, 23),
            datetime(2026, 3, 29),
            exclude_inferred_price_quality=False,
        )

        if result:
            row = result[0]
            assert len(row) == 8
            # Check types
            assert isinstance(row[0], str)  # date
            assert isinstance(row[1], str)  # match_id
            assert isinstance(row[2], str)  # sport
            assert isinstance(row[3], float)  # open_fav_price
            assert isinstance(row[4], float)  # tipoff_fav_price
            assert isinstance(row[5], (int, float))  # token_id
            assert isinstance(row[6], bool)  # can_settle
            assert isinstance(row[7], str)  # price_quality
