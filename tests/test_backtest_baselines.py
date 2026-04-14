"""Tests for baseline strategy implementations."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from backtest.backtest_baselines import (
    baseline_buy_at_open,
    baseline_buy_at_tipoff,
    baseline_buy_first_ingame,
)


@pytest.fixture
def game_data():
    """Create game data with trades and events."""
    base_time = datetime(2026, 3, 23, 19, 30, 0)

    trades_df = pd.DataFrame(
        {
            "datetime": [
                base_time + timedelta(minutes=1),
                base_time + timedelta(minutes=2),
                base_time + timedelta(minutes=5),
                base_time + timedelta(minutes=10),
            ],
            "price": [0.92, 0.91, 0.90, 0.93],
        }
    )

    events = [
        {
            "datetime": "2026-03-23T20:30:00",
            "period": 4,
            "away_score": 105,
            "home_score": 102,
        },
    ]

    manifest = {
        "match_id": "nba_game_1",
        "sport": "nba",
        "away_team": "LAL",
        "home_team": "BOS",
    }

    return {
        "base_time": base_time,
        "trades_df": trades_df,
        "events": events,
        "manifest": manifest,
        "tipoff_time": base_time,
        "game_end": base_time + timedelta(hours=2, minutes=30),
    }


def test_baseline_buy_at_open(game_data):
    """Test buy-at-open baseline."""
    result = baseline_buy_at_open(
        open_price=0.92,
        trades_df=game_data["trades_df"],
        tipoff_time=game_data["tipoff_time"],
        game_end=game_data["game_end"],
        manifest=game_data["manifest"],
        events=game_data["events"],
        sport="nba",
        fee_pct=0.002,
        settings=None,
        open_favorite_team="LAL",
    )

    assert result["entry_price"] == 0.92
    assert result["exit_price"] == 0.93  # Last in-game trade
    assert result["hold_seconds"] > 0
    assert result["settlement_occurred"] is True


def test_baseline_buy_at_tipoff(game_data):
    """Test buy-at-tipoff baseline."""
    result = baseline_buy_at_tipoff(
        tipoff_price=0.91,
        trades_df=game_data["trades_df"],
        tipoff_time=game_data["tipoff_time"],
        game_end=game_data["game_end"],
        manifest=game_data["manifest"],
        events=game_data["events"],
        sport="nba",
        fee_pct=0.002,
        settings=None,
        open_favorite_team="LAL",
    )

    assert result["entry_price"] == 0.91
    assert result["exit_price"] == 0.93  # Last in-game trade
    assert result["hold_seconds"] > 0
    assert result["settlement_occurred"] is True


def test_baseline_buy_first_ingame(game_data):
    """Test buy-first-in-game baseline."""
    result = baseline_buy_first_ingame(
        trades_df=game_data["trades_df"],
        tipoff_time=game_data["tipoff_time"],
        game_end=game_data["game_end"],
        manifest=game_data["manifest"],
        events=game_data["events"],
        sport="nba",
        fee_pct=0.002,
        settings=None,
        open_favorite_team="LAL",
    )

    assert result["entry_price"] == 0.92  # First in-game trade
    assert result["exit_price"] == 0.93  # Last in-game trade
    assert result["hold_seconds"] > 0
    assert result["settlement_occurred"] is True


def test_baseline_buy_at_open_no_trades(game_data):
    """Test buy-at-open with no trades."""
    result = baseline_buy_at_open(
        open_price=0.92,
        trades_df=pd.DataFrame({"datetime": [], "price": []}),
        tipoff_time=game_data["tipoff_time"],
        game_end=game_data["game_end"],
        manifest=game_data["manifest"],
        events=game_data["events"],
        sport="nba",
        fee_pct=0.002,
        settings=None,
    )

    assert result["entry_price"] == 0.92
    assert result["exit_price"] is None
    assert result["hold_seconds"] == 0


def test_baseline_buy_first_ingame_no_trades(game_data):
    """Test buy-first-in-game with no trades."""
    result = baseline_buy_first_ingame(
        trades_df=pd.DataFrame({"datetime": [], "price": []}),
        tipoff_time=game_data["tipoff_time"],
        game_end=game_data["game_end"],
        manifest=game_data["manifest"],
        events=game_data["events"],
        sport="nba",
        fee_pct=0.002,
        settings=None,
    )

    assert result["entry_price"] is None
    assert result["exit_price"] is None
    assert result["hold_seconds"] == 0


def test_baseline_roi_comparison(game_data):
    """Test that baselines compute ROI correctly for comparison."""
    base_time = game_data["base_time"]
    trades_df = pd.DataFrame(
        {
            "datetime": [
                base_time + timedelta(minutes=1),
                base_time + timedelta(minutes=10),
            ],
            "price": [0.90, 0.95],
        }
    )

    result_open = baseline_buy_at_open(
        open_price=0.90,
        trades_df=trades_df,
        tipoff_time=game_data["tipoff_time"],
        game_end=game_data["game_end"],
        manifest=game_data["manifest"],
        events=game_data["events"],
        sport="nba",
        fee_pct=0.0,  # No fee for simplicity
        settings=None,
    )

    # 5-cent gain on 90-cent entry = 5.56% ROI (roughly)
    assert result_open["roi_pct"] > 0
    assert result_open["gross_pnl_cents"] > 0


def test_baseline_buy_at_open_maker_fee(game_data):
    """Test buy-at-open with maker fee model → zero fee cost."""
    result = baseline_buy_at_open(
        open_price=0.92,
        trades_df=game_data["trades_df"],
        tipoff_time=game_data["tipoff_time"],
        game_end=game_data["game_end"],
        manifest=game_data["manifest"],
        events=game_data["events"],
        sport="nba",
        fee_pct=0.0,
        settings=None,
        fee_model="maker",
    )

    assert result["fee_cost_cents"] == 0.0
    assert result["gross_pnl_cents"] == result["net_pnl_cents"]


def test_baseline_buy_at_tipoff_no_trades(game_data):
    """Test buy-at-tipoff returns zero-PnL dict when trades_df is empty."""
    result = baseline_buy_at_tipoff(
        tipoff_price=0.91,
        trades_df=pd.DataFrame({"datetime": [], "price": []}),
        tipoff_time=game_data["tipoff_time"],
        game_end=game_data["game_end"],
        manifest=game_data["manifest"],
        events=game_data["events"],
        sport="nba",
        fee_pct=0.002,
        settings=None,
    )

    assert result["entry_price"] == 0.91
    assert result["exit_price"] is None
    assert result["hold_seconds"] == 0
    assert result["gross_pnl_cents"] == 0
    assert result["net_pnl_cents"] == 0


def test_baseline_buy_at_tipoff_maker_fee(game_data):
    """Test buy-at-tipoff with maker fee model passes fee_model through."""
    result = baseline_buy_at_tipoff(
        tipoff_price=0.91,
        trades_df=game_data["trades_df"],
        tipoff_time=game_data["tipoff_time"],
        game_end=game_data["game_end"],
        manifest=game_data["manifest"],
        events=game_data["events"],
        sport="nba",
        fee_pct=0.0,
        settings=None,
        fee_model="maker",
    )

    assert result["fee_cost_cents"] == 0.0
    assert result["gross_pnl_cents"] == result["net_pnl_cents"]


def test_baseline_buy_at_open_pregame_only_trades(game_data):
    """Test buy-at-open when all trades are pregame (in_game empty)."""
    base_time = game_data["base_time"]
    pregame_only = pd.DataFrame(
        {
            "datetime": [
                base_time - timedelta(minutes=10),
                base_time - timedelta(minutes=5),
            ],
            "price": [0.90, 0.91],
        }
    )

    result = baseline_buy_at_open(
        open_price=0.90,
        trades_df=pregame_only,
        tipoff_time=game_data["tipoff_time"],
        game_end=game_data["game_end"],
        manifest=game_data["manifest"],
        events=game_data["events"],
        sport="nba",
        fee_pct=0.002,
        settings=None,
    )

    # No in-game trades → exit is None
    assert result["exit_price"] is None
    assert result["hold_seconds"] == 0
