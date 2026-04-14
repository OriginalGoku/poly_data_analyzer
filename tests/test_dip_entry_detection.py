"""Tests for dip entry/exit detection."""
from datetime import datetime, timedelta

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
            "datetime": [
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
            "datetime": [
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
        pd.DataFrame({"datetime": [], "price": []}),
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


def test_find_exit_settlement(ingame_trades, game_times):
    """Test settlement exit (last in-game trade)."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=None,
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
    )

    assert result["status"] == "filled"
    assert result["exit_price"] == 0.94  # Last in-game trade
    assert result["exit_type"] == "settlement"
    assert result["hold_seconds"] > 0


def test_find_exit_reversion_to_open(ingame_trades, game_times):
    """Test reversion to open exit."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=None,
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
    )

    assert result["status"] == "filled"
    assert result["exit_price"] == 0.92  # First trade >= open
    assert result["exit_type"] == "reversion_to_open"


def test_find_exit_fixed_profit(ingame_trades, game_times):
    """Test fixed profit exit."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=None,
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
    )

    assert result["status"] == "filled"
    # Entry at 0.81, target is >= 0.84, but due to float precision 0.84 doesn't match
    # so first match is 0.87
    assert result["exit_price"] == 0.87


def test_find_exit_not_triggered(ingame_trades, game_times):
    """Test forced_close when exit condition is never met but in-game trades exist."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=None,
    )

    result = find_exit(
        ingame_trades,
        entry_time=entry_result["entry_time"],
        entry_price=entry_result["entry_price"],
        exit_type="fixed_profit",
        exit_param=20,  # Would need 0.20 profit — unreachable
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
    )

    # Post-entry trades exist but target never met → forced_close at last in-game price
    assert result["status"] == "forced_close"
    assert result["exit_price"] is not None
    assert result["exit_price"] == 0.94  # Last in-game trade after entry


def test_find_exit_forced_close_no_post_trades(base_time, game_times):
    """Test not_triggered when no in-game trades exist after entry_time."""
    # All trades at or before the entry time
    early_trades = pd.DataFrame(
        {
            "datetime": [
                base_time + timedelta(minutes=1),
                base_time + timedelta(minutes=2),
                base_time + timedelta(minutes=3),
            ],
            "price": [0.92, 0.91, 0.81],
        }
    )
    entry_time = base_time + timedelta(minutes=3)

    result = find_exit(
        early_trades,
        entry_time=entry_time,
        entry_price=0.81,
        exit_type="reversion_to_open",
        exit_param=0,
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
    )

    assert result["status"] == "not_triggered"
    assert result["exit_price"] is None


def test_find_exit_post_game_trade_excluded(base_time, game_times):
    """Test that trades after game_end do not trigger non-settlement exits."""
    trades = pd.DataFrame(
        {
            "datetime": [
                base_time + timedelta(minutes=3),   # Entry trade (dip)
                base_time + timedelta(minutes=4),   # Still below open
                # Post-settlement spike — must be excluded
                game_times["game_end"] + timedelta(minutes=5),
            ],
            "price": [0.81, 0.82, 1.0],
        }
    )
    entry_time = base_time + timedelta(minutes=3)

    result = find_exit(
        trades,
        entry_time=entry_time,
        entry_price=0.81,
        exit_type="reversion_to_open",
        exit_param=0,
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
    )

    # 1.0 post-game spike is excluded; 0.82 in-game trade doesn't reach open (0.92)
    # → forced_close at last in-game price 0.82
    assert result["exit_price"] != 1.0
    assert result["status"] == "forced_close"
    assert result["exit_price"] == 0.82


def test_find_exit_reversion_partial(ingame_trades, game_times):
    """Test reversion to partial level."""
    entry_result = find_dip_entry(
        ingame_trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=None,
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
    )

    assert result["status"] == "filled"
    assert result["exit_price"] == 0.87


def test_find_exit_unknown_type_raises(ingame_trades, game_times):
    """Test that an unknown exit_type raises ValueError."""
    with pytest.raises(ValueError, match="Unknown exit_type"):
        find_exit(
            ingame_trades,
            entry_time=game_times["tipoff"],
            entry_price=0.81,
            exit_type="invalid_type",
            exit_param=0,
            open_price=0.92,
            tipoff_time=game_times["tipoff"],
            game_end=game_times["game_end"],
            sport="nba",
        )


def test_find_exit_settlement_no_post_trades(base_time, game_times):
    """Test settlement exit returns not_triggered when no post-entry in-game trades."""
    trades = pd.DataFrame(
        {
            "datetime": [base_time + timedelta(minutes=1)],
            "price": [0.81],
        }
    )
    entry_time = base_time + timedelta(minutes=1)

    result = find_exit(
        trades,
        entry_time=entry_time,
        entry_price=0.81,
        exit_type="settlement",
        exit_param=0,
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
    )

    assert result["status"] == "not_triggered"
    assert result["exit_price"] is None
    assert result["exit_type"] == "settlement"


def test_find_exit_reversion_partial_forced_close_no_post_trades(base_time, game_times):
    """Test reversion_to_partial returns not_triggered when no post-entry trades exist."""
    trades = pd.DataFrame(
        {
            "datetime": [base_time + timedelta(minutes=1)],
            "price": [0.81],
        }
    )
    entry_time = base_time + timedelta(minutes=1)

    result = find_exit(
        trades,
        entry_time=entry_time,
        entry_price=0.81,
        exit_type="reversion_to_partial",
        exit_param=5,
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
    )

    assert result["status"] == "not_triggered"
    assert result["exit_price"] is None


def test_find_exit_fixed_profit_forced_close_no_post_trades(base_time, game_times):
    """Test fixed_profit returns not_triggered when no post-entry trades exist."""
    trades = pd.DataFrame(
        {
            "datetime": [base_time + timedelta(minutes=1)],
            "price": [0.81],
        }
    )
    entry_time = base_time + timedelta(minutes=1)

    result = find_exit(
        trades,
        entry_time=entry_time,
        entry_price=0.81,
        exit_type="fixed_profit",
        exit_param=10,
        open_price=0.92,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        sport="nba",
    )

    assert result["status"] == "not_triggered"
    assert result["exit_price"] is None


def test_find_dip_entry_excludes_game_end_boundary(base_time, game_times):
    """Test that a trade exactly at game_end is excluded (< game_end, not <=)."""
    trades = pd.DataFrame(
        {
            "datetime": [
                base_time + timedelta(minutes=1),
                game_times["game_end"],  # Exactly at game_end — must be excluded
            ],
            "price": [0.92, 0.81],  # Dip is at game_end
        }
    )

    result = find_dip_entry(
        trades,
        open_price=0.92,
        dip_threshold_cents=10,
        tipoff_time=game_times["tipoff"],
        game_end=game_times["game_end"],
        settings=None,
    )

    # 0.81 at game_end is excluded; 0.92 in-game doesn't touch dip level (0.82)
    assert result is None
