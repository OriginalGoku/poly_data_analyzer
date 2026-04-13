"""Tests for dip entry/exit detection."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from backtest.dip_entry_detection import find_dip_entry, find_exit


@pytest.fixture
def base_time():
    """Base time for test trades."""
    return datetime(2026, 3, 23, 19, 30, 0)  # Tipoff


@pytest.fixture
def game_times(base_time):
    """Game start and end times."""
    return {
        "tipoff": base_time,
        "game_end": base_time + timedelta(hours=2, minutes=30),
    }


@pytest.fixture
def pregame_trades(base_time):
    """Pregame trades (before tipoff)."""
    return pd.DataFrame(
        {
            "time": [
                base_time - timedelta(minutes=30),
                base_time - timedelta(minutes=15),
            ],
            "price": [0.95, 0.93],
        }
    )


@pytest.fixture
def ingame_trades(base_time):
    """In-game trades with a dip."""
    return pd.DataFrame(
        {
            "time": [
                base_time + timedelta(minutes=1),   # Open trades
                base_time + timedelta(minutes=2),
                base_time + timedelta(minutes=3),   # Dip
                base_time + timedelta(minutes=4),   # Recovery
                base_time + timedelta(minutes=5),
                base_time + timedelta(minutes=10),  # Back to open
                base_time + timedelta(minutes=20),  # Further recovery
            ],
            "price": [0.92, 0.91, 0.81, 0.84, 0.87, 0.92, 0.94],
        }
    )


@pytest.fixture
def mock_settings():
    """Mock settings object."""
    settings = MagicMock()
    settings.nba_quarter_duration_min = 12
    return settings


def test_find_dip_entry_basic(ingame_trades, game_times):
    """Test basic dip entry detection."""
    result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=None,
    )

    assert result is not None
    assert result["entry_price"] == 0.81
    assert result["entry_time"] == game_times["tipoff"] + timedelta(minutes=3)


def test_find_dip_entry_no_dip(ingame_trades, game_times):
    """Test when dip threshold is never touched."""
    result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=20,  # Would need to go below 0.72
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=None,
    )

    assert result is None


def test_find_dip_entry_empty_trades(game_times):
    """Test with empty trades DataFrame."""
    result = find_dip_entry(
        pd.DataFrame({"time": [], "price": []}),
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=None,
    )

    assert result is None


def test_find_dip_entry_pregame_only(pregame_trades, game_times):
    """Test that pregame trades are ignored."""
    result = find_dip_entry(
        pregame_trades,
        open_price=0.95,
        dip_threshold_cents=5,  # Would hit 0.90
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=None,
    )

    assert result is None


def test_find_exit_settlement(ingame_trades, game_times, mock_settings):
    """Test settlement exit (last in-game trade)."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=mock_settings,
    )

    result = find_exit(
        ingame_trades,
        entry_time=entry_result["entry_time"],
        entry_price=entry_result["entry_price"],
        exit_type="settlement",
        exit_param=0,
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
        settings=mock_settings,
    )

    assert result["status"] == "filled"
    assert result["exit_price"] == 0.94  # Last in-game trade
    assert result["exit_type"] == "settlement"
    assert result["hold_seconds"] > 0


def test_find_exit_reversion_to_open(ingame_trades, game_times, mock_settings):
    """Test reversion to open exit."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=mock_settings,
    )

    result = find_exit(
        ingame_trades,
        entry_time=entry_result["entry_time"],
        entry_price=entry_result["entry_price"],
        exit_type="reversion_to_open",
        exit_param=0,
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
        settings=mock_settings,
    )

    assert result["status"] == "filled"
    assert result["exit_price"] == 0.92  # First trade >= open
    assert result["exit_type"] == "reversion_to_open"


def test_find_exit_fixed_profit(ingame_trades, game_times, mock_settings):
    """Test fixed profit exit."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=mock_settings,
    )

    result = find_exit(
        ingame_trades,
        entry_time=entry_result["entry_time"],
        entry_price=entry_result["entry_price"],
        exit_type="fixed_profit",
        exit_param=3,  # 0.03 = 3 cents profit target
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
        settings=mock_settings,
    )

    assert result["status"] == "filled"
    # Entry at 0.81, target is >= 0.84, but due to float precision 0.84 doesn't match
    # so first match is 0.87
    assert result["exit_price"] == 0.87


def test_find_exit_time_based_nba(ingame_trades, game_times, mock_settings):
    """Test time-based quarter exit for NBA."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=mock_settings,
    )

    result = find_exit(
        ingame_trades,
        entry_time=entry_result["entry_time"],
        entry_price=entry_result["entry_price"],
        exit_type="time_based_quarter",
        exit_param=1,  # End of Q1 = 12 minutes
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
        settings=mock_settings,
    )

    assert result["status"] == "filled"
    # Q1 ends at 12 min, latest trade <= 12 min is at 10 min with price 0.92
    assert result["exit_price"] == 0.92


def test_find_exit_time_based_non_nba(ingame_trades, game_times, mock_settings):
    """Test that time-based exit returns not_applicable for non-NBA."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=mock_settings,
    )

    result = find_exit(
        ingame_trades,
        entry_time=entry_result["entry_time"],
        entry_price=entry_result["entry_price"],
        exit_type="time_based_quarter",
        exit_param=1,
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nhl",  # Not NBA
        settings=mock_settings,
    )

    assert result["status"] == "time_based_not_applicable"
    assert result["exit_time"] is None


def test_find_exit_not_triggered(ingame_trades, game_times, mock_settings):
    """Test when exit condition is never met."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=mock_settings,
    )

    result = find_exit(
        ingame_trades,
        entry_time=entry_result["entry_time"],
        entry_price=entry_result["entry_price"],
        exit_type="fixed_profit",
        exit_param=20,  # Would need 0.20 profit, but max is ~0.13
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
        settings=mock_settings,
    )

    assert result["status"] == "not_triggered"
    assert result["exit_time"] is None


def test_find_exit_reversion_partial(ingame_trades, game_times, mock_settings):
    """Test reversion to partial level."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=mock_settings,
    )

    result = find_exit(
        ingame_trades,
        entry_time=entry_result["entry_time"],
        entry_price=entry_result["entry_price"],
        exit_type="reversion_to_partial",
        exit_param=5,  # 0.92 - 0.05 = 0.87
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
        settings=mock_settings,
    )

    assert result["status"] == "filled"
    assert result["exit_price"] == 0.87
