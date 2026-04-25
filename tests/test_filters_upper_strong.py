"""Tests for backtest.filters.upper_strong universe filter."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from backtest.contracts import GameMeta
from backtest.filters.upper_strong import upper_strong
from backtest.registry import UNIVERSE_FILTERS
import backtest.filters  # noqa: F401  (registers filter)


@pytest.fixture
def mock_analytics_df():
    base_date = datetime(2026, 3, 23)
    return pd.DataFrame(
        [
            {
                "date": base_date.isoformat(),
                "match_id": "nba_game_1",
                "sport": "nba",
                "open_favorite_price": 0.90,
                "tipoff_favorite_price": 0.89,
                "open_favorite_token_id": "tok-1",
                "open_favorite_team": "LAL",
                "has_events": True,
                "has_final_score": True,
                "price_quality": "good",
                "in_game_notional_usdc": 12345.0,
            },
            {
                "date": (base_date + timedelta(days=1)).isoformat(),
                "match_id": "nba_game_2",
                "sport": "nba",
                "open_favorite_price": 0.80,
                "tipoff_favorite_price": 0.80,
                "open_favorite_token_id": "tok-2",
                "open_favorite_team": "BOS",
                "has_events": True,
                "has_final_score": True,
                "price_quality": "good",
                "in_game_notional_usdc": 5000.0,
            },
            {
                "date": (base_date + timedelta(days=2)).isoformat(),
                "match_id": "nba_game_3",
                "sport": "nba",
                "open_favorite_price": 0.85,  # exactly threshold
                "tipoff_favorite_price": 0.85,
                "open_favorite_token_id": "tok-3",
                "open_favorite_team": "MIA",
                "has_events": True,
                "has_final_score": True,
                "price_quality": "good",
                "in_game_notional_usdc": 5000.0,
            },
            {
                "date": (base_date + timedelta(days=3)).isoformat(),
                "match_id": "nba_game_4",
                "sport": "nba",
                "open_favorite_price": 0.95,
                "tipoff_favorite_price": 0.94,
                "open_favorite_token_id": "tok-4",
                "open_favorite_team": "Tie",
                "has_events": True,
                "has_final_score": True,
                "price_quality": "good",
                "in_game_notional_usdc": 5000.0,
            },
            {
                "date": (base_date + timedelta(days=4)).isoformat(),
                "match_id": "nba_game_5",
                "sport": "nba",
                "open_favorite_price": 0.92,
                "tipoff_favorite_price": 0.91,
                "open_favorite_token_id": "tok-5",
                "open_favorite_team": "GSW",
                "has_events": True,
                "has_final_score": True,
                "price_quality": "inferred",
                "in_game_notional_usdc": 5000.0,
            },
            {
                "date": (base_date + timedelta(days=5)).isoformat(),
                "match_id": "nba_game_6",
                "sport": "nba",
                "open_favorite_price": 0.88,
                "tipoff_favorite_price": 0.87,
                "open_favorite_token_id": "tok-6",
                "open_favorite_team": "DEN",
                "has_events": False,
                "has_final_score": False,
                "price_quality": "good",
                "in_game_notional_usdc": 5000.0,
            },
            {
                "date": (base_date + timedelta(days=6)).isoformat(),
                "match_id": "nba_game_7",
                "sport": "nba",
                "open_favorite_price": 0.91,
                "tipoff_favorite_price": 0.90,
                "open_favorite_token_id": "tok-7",
                "open_favorite_team": "PHX",
                "has_events": True,
                "has_final_score": True,
                "price_quality": "good",
                "in_game_notional_usdc": 0,  # zero in-game volume
            },
        ]
    )


@pytest.fixture
def patch_load(mock_analytics_df):
    with patch(
        "backtest.filters.upper_strong.load_game_analytics",
        return_value=mock_analytics_df,
    ) as m:
        yield m


def test_basic_threshold_and_tie_exclusion(patch_load):
    result = upper_strong(
        datetime(2026, 3, 23),
        datetime(2026, 3, 30),
        {"exclude_inferred_price_quality": False},
    )
    ids = [g.match_id for g in result]
    # Excluded: game_2 (<=), game_3 (==), game_4 (Tie), game_7 (zero vol)
    assert ids == ["nba_game_1", "nba_game_5", "nba_game_6"]


def test_excludes_inferred_by_default(patch_load):
    result = upper_strong(
        datetime(2026, 3, 23),
        datetime(2026, 3, 30),
        {},
    )
    ids = [g.match_id for g in result]
    assert ids == ["nba_game_1", "nba_game_6"]


def test_zero_in_game_volume_excluded(patch_load):
    result = upper_strong(
        datetime(2026, 3, 23),
        datetime(2026, 3, 30),
        {"exclude_inferred_price_quality": False},
    )
    assert all(g.match_id != "nba_game_7" for g in result)


def test_date_range_bounds(patch_load):
    result = upper_strong(
        datetime(2026, 4, 1),
        datetime(2026, 4, 30),
        {},
    )
    assert result == []


def test_can_settle_flag(patch_load):
    result = upper_strong(
        datetime(2026, 3, 23),
        datetime(2026, 3, 30),
        {"exclude_inferred_price_quality": False},
    )
    by_id = {g.match_id: g for g in result}
    assert by_id["nba_game_1"].can_settle is True
    assert by_id["nba_game_5"].can_settle is True
    assert by_id["nba_game_6"].can_settle is False


def test_returns_game_meta_with_full_fields(patch_load):
    result = upper_strong(
        datetime(2026, 3, 23),
        datetime(2026, 3, 30),
        {"exclude_inferred_price_quality": False},
    )
    g = result[0]
    assert isinstance(g, GameMeta)
    assert g.date == datetime(2026, 3, 23).isoformat()
    assert g.match_id == "nba_game_1"
    assert g.sport == "nba"
    assert g.open_fav_price == pytest.approx(0.90)
    assert g.tipoff_fav_price == pytest.approx(0.89)
    assert g.open_fav_token_id == "tok-1"
    assert g.price_quality == "good"
    assert g.open_favorite_team == "LAL"
    assert g.can_settle is True


def test_missing_tipoff_falls_back_to_open(mock_analytics_df):
    df = mock_analytics_df.drop(columns=["tipoff_favorite_price"])
    with patch(
        "backtest.filters.upper_strong.load_game_analytics", return_value=df
    ):
        result = upper_strong(
            datetime(2026, 3, 23),
            datetime(2026, 3, 30),
            {"exclude_inferred_price_quality": False},
        )
    assert result[0].tipoff_fav_price == pytest.approx(result[0].open_fav_price)


def test_registered_in_universe_filters():
    assert UNIVERSE_FILTERS["upper_strong"] is upper_strong
