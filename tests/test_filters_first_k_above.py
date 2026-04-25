"""Tests for backtest.filters.first_k_above universe filter."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from backtest.contracts import GameMeta
from backtest.filters.first_k_above import first_k_above
from backtest.registry import UNIVERSE_FILTERS
import backtest.filters  # noqa: F401  (registers filter)


BASE_DATE = datetime(2026, 3, 23)


def _row(match_id, day_offset, fav_team="LAL", **overrides):
    base = {
        "date": (BASE_DATE + timedelta(days=day_offset)).isoformat(),
        "match_id": match_id,
        "sport": "nba",
        "open_favorite_price": 0.90,
        "tipoff_favorite_price": 0.89,
        "open_favorite_token_id": "tok-1",
        "open_favorite_team": fav_team,
        "has_events": True,
        "has_final_score": True,
        "price_quality": "good",
        "in_game_notional_usdc": 5000.0,
    }
    base.update(overrides)
    return base


def _game(prices, fav_team="LAL", tipoff=None):
    """Build a fake load_game return with K favorite-side trades at given prices."""
    if tipoff is None:
        tipoff = pd.Timestamp("2026-03-23T19:00:00", tz="UTC")
    rows = []
    # one pre-tipoff trade (should be ignored)
    rows.append(
        {
            "datetime": tipoff - pd.Timedelta(minutes=5),
            "team": fav_team,
            "price": 0.99,
        }
    )
    # one underdog post-tipoff trade (should be ignored)
    rows.append(
        {
            "datetime": tipoff + pd.Timedelta(seconds=1),
            "team": "OTHER",
            "price": 0.10,
        }
    )
    for i, p in enumerate(prices):
        rows.append(
            {
                "datetime": tipoff + pd.Timedelta(seconds=10 + i),
                "team": fav_team,
                "price": p,
            }
        )
    trades_df = pd.DataFrame(rows)
    events = [
        {"eventType": "score", "time_actual_dt": tipoff},
    ]
    return {"trades_df": trades_df, "events": events}


@pytest.fixture
def patch_loaders():
    """Provide both load_game_analytics and load_game patches; tests configure them."""
    with patch(
        "backtest.filters.first_k_above.load_game_analytics"
    ) as m_an, patch(
        "backtest.filters.first_k_above.load_game"
    ) as m_g:
        yield m_an, m_g


def test_fewer_than_k_excluded(patch_loaders):
    m_an, m_g = patch_loaders
    m_an.return_value = pd.DataFrame([_row("g1", 0)])
    m_g.return_value = _game([0.90, 0.91])  # only 2 trades, k=3
    result = first_k_above(
        BASE_DATE, BASE_DATE + timedelta(days=1), {"k": 3, "min_price": 0.85}
    )
    assert result == []


def test_exactly_k_all_above_included(patch_loaders):
    m_an, m_g = patch_loaders
    m_an.return_value = pd.DataFrame([_row("g1", 0)])
    m_g.return_value = _game([0.90, 0.91, 0.92])
    result = first_k_above(
        BASE_DATE, BASE_DATE + timedelta(days=1), {"k": 3, "min_price": 0.85}
    )
    assert [g.match_id for g in result] == ["g1"]
    assert isinstance(result[0], GameMeta)


def test_k_with_one_below_excluded(patch_loaders):
    m_an, m_g = patch_loaders
    m_an.return_value = pd.DataFrame([_row("g1", 0)])
    m_g.return_value = _game([0.90, 0.84, 0.92])  # middle below threshold
    result = first_k_above(
        BASE_DATE, BASE_DATE + timedelta(days=1), {"k": 3, "min_price": 0.85}
    )
    assert result == []


def test_kth_at_exactly_min_price_included(patch_loaders):
    m_an, m_g = patch_loaders
    m_an.return_value = pd.DataFrame([_row("g1", 0)])
    m_g.return_value = _game([0.90, 0.88, 0.85])
    result = first_k_above(
        BASE_DATE, BASE_DATE + timedelta(days=1), {"k": 3, "min_price": 0.85}
    )
    assert [g.match_id for g in result] == ["g1"]


def test_pre_tipoff_and_underdog_trades_ignored(patch_loaders):
    """The 1st favorite trade post-tipoff is the only one that counts (k=1)."""
    m_an, m_g = patch_loaders
    m_an.return_value = pd.DataFrame([_row("g1", 0)])
    # _game injects a 0.99 pre-tipoff and a 0.10 underdog post-tipoff before favorites.
    m_g.return_value = _game([0.86])
    result = first_k_above(
        BASE_DATE, BASE_DATE + timedelta(days=1), {"k": 1, "min_price": 0.85}
    )
    assert [g.match_id for g in result] == ["g1"]


def test_tie_favorite_excluded(patch_loaders):
    m_an, m_g = patch_loaders
    m_an.return_value = pd.DataFrame([_row("g1", 0, fav_team="Tie")])
    m_g.return_value = _game([0.90, 0.91, 0.92])
    result = first_k_above(
        BASE_DATE, BASE_DATE + timedelta(days=1), {"k": 3, "min_price": 0.85}
    )
    assert result == []


def test_date_range_bounds(patch_loaders):
    m_an, m_g = patch_loaders
    m_an.return_value = pd.DataFrame([_row("g1", 0)])
    m_g.return_value = _game([0.90, 0.91, 0.92])
    result = first_k_above(
        datetime(2026, 4, 1), datetime(2026, 4, 30), {"k": 3, "min_price": 0.85}
    )
    assert result == []


def test_inferred_excluded_by_default(patch_loaders):
    m_an, m_g = patch_loaders
    m_an.return_value = pd.DataFrame(
        [_row("g1", 0, price_quality="inferred")]
    )
    m_g.return_value = _game([0.90, 0.91, 0.92])
    result = first_k_above(
        BASE_DATE, BASE_DATE + timedelta(days=1), {"k": 3, "min_price": 0.85}
    )
    assert result == []


def test_registered_in_universe_filters():
    assert UNIVERSE_FILTERS["first_k_above"] is first_k_above
    assert "upper_strong" in UNIVERSE_FILTERS
