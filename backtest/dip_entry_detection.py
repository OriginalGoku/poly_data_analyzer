"""Trade-level entry/exit detection for dip buy strategy."""
from datetime import datetime
from typing import Dict, Literal, Optional

import pandas as pd


def find_dip_entry(
    trades_df: pd.DataFrame,
    open_price: float,
    dip_threshold_cents: int,
    tipoff_time: datetime,
    game_end: datetime,
    settings,
) -> Optional[Dict]:
    """Find first in-game dip entry touch.

    Filters to in-game trades (after tipoff), finds first touch at or below
    (open_price - dip_threshold_cents/100).

    Args:
        trades_df: DataFrame with 'time', 'price' columns
        open_price: Entry open price (0-1 range)
        dip_threshold_cents: Dip threshold in cents (e.g., 10 = 0.10)
        tipoff_time: Game start time
        game_end: Game end time
        settings: ChartSettings instance (unused in v1, for future compatibility)

    Returns:
        Dict with keys: entry_time, entry_price; or None if never triggered.
    """
    if trades_df.empty:
        return None

    dip_threshold = dip_threshold_cents / 100.0
    dip_level = open_price - dip_threshold

    # Filter to in-game trades (after tipoff, before game_end)
    in_game = trades_df[
        (trades_df["datetime"] >= tipoff_time) & (trades_df["datetime"] < game_end)
    ].copy()

    if in_game.empty:
        return None

    # Find first touch at or below dip level
    dip_hit = in_game[in_game["price"] <= dip_level]
    if dip_hit.empty:
        return None

    entry = dip_hit.iloc[0]
    return {
        "entry_time": entry["datetime"],
        "entry_price": entry["price"],
    }


def find_exit(
    trades_df: pd.DataFrame,
    entry_time: datetime,
    entry_price: float,
    exit_type: Literal[
        "settlement",
        "reversion_to_open",
        "reversion_to_partial",
        "fixed_profit",
        "time_based_quarter",
    ],
    exit_param: int,
    open_price: float,
    tipoff_time: datetime,
    game_end: datetime,
    sport: str,
    settings,
) -> Dict:
    """Find exit condition based on exit_type.

    Args:
        trades_df: DataFrame with 'time', 'price' columns
        entry_time: Entry trade time
        entry_price: Entry price (0-1 range)
        exit_type: Exit strategy type
        exit_param: Exit parameter (cents for reversion_to_partial/fixed_profit,
                   quarter number for time_based_quarter)
        open_price: Original open price (for reversion_to_open)
        tipoff_time: Game start time
        game_end: Game end time
        sport: Sport code (e.g., "nba", "nhl", "mlb")
        settings: ChartSettings instance with sport durations

    Returns:
        Dict with keys: exit_time, exit_price, exit_type, hold_seconds, status.
    """
    post_entry = trades_df[trades_df["datetime"] > entry_time].copy()

    if exit_type == "settlement":
        # Exit at last in-game trade before game_end
        in_game_post = post_entry[post_entry["datetime"] < game_end]
        if in_game_post.empty:
            return {
                "exit_time": None,
                "exit_price": None,
                "exit_type": "settlement",
                "hold_seconds": 0,
                "status": "not_triggered",
            }
        exit_trade = in_game_post.iloc[-1]
        return {
            "exit_time": exit_trade["datetime"],
            "exit_price": exit_trade["price"],
            "exit_type": "settlement",
            "hold_seconds": int((exit_trade["datetime"] - entry_time).total_seconds()),
            "status": "filled",
        }

    elif exit_type == "reversion_to_open":
        # Exit at first trade >= open_price
        revert = post_entry[post_entry["price"] >= open_price]
        if revert.empty:
            return {
                "exit_time": None,
                "exit_price": None,
                "exit_type": "reversion_to_open",
                "hold_seconds": 0,
                "status": "not_triggered",
            }
        exit_trade = revert.iloc[0]
        return {
            "exit_time": exit_trade["datetime"],
            "exit_price": exit_trade["price"],
            "exit_type": "reversion_to_open",
            "hold_seconds": int((exit_trade["datetime"] - entry_time).total_seconds()),
            "status": "filled",
        }

    elif exit_type == "reversion_to_partial":
        # Exit at first trade >= (open_price - exit_param/100)
        partial_target = open_price - (exit_param / 100.0)
        revert = post_entry[post_entry["price"] >= partial_target]
        if revert.empty:
            return {
                "exit_time": None,
                "exit_price": None,
                "exit_type": "reversion_to_partial",
                "hold_seconds": 0,
                "status": "not_triggered",
            }
        exit_trade = revert.iloc[0]
        return {
            "exit_time": exit_trade["datetime"],
            "exit_price": exit_trade["price"],
            "exit_type": "reversion_to_partial",
            "hold_seconds": int((exit_trade["datetime"] - entry_time).total_seconds()),
            "status": "filled",
        }

    elif exit_type == "fixed_profit":
        # Exit at first trade >= (entry_price + exit_param/100)
        profit_target = entry_price + (exit_param / 100.0)
        profit = post_entry[post_entry["price"] >= profit_target]
        if profit.empty:
            return {
                "exit_time": None,
                "exit_price": None,
                "exit_type": "fixed_profit",
                "hold_seconds": 0,
                "status": "not_triggered",
            }
        exit_trade = profit.iloc[0]
        return {
            "exit_time": exit_trade["datetime"],
            "exit_price": exit_trade["price"],
            "exit_type": "fixed_profit",
            "hold_seconds": int((exit_trade["datetime"] - entry_time).total_seconds()),
            "status": "filled",
        }

    elif exit_type == "time_based_quarter":
        # NBA only: exit at quarter-end (NBA quarter = 12 min)
        if sport != "nba":
            return {
                "exit_time": None,
                "exit_price": None,
                "exit_type": "time_based_quarter",
                "hold_seconds": 0,
                "status": "time_based_not_applicable",
            }

        quarter_num = exit_param
        quarter_duration_min = settings.nba_quarter_duration_min
        quarter_end = tipoff_time + pd.Timedelta(
            minutes=quarter_num * quarter_duration_min
        )

        # Find last trade at or before quarter_end
        valid = post_entry[post_entry["datetime"] <= quarter_end]
        if valid.empty:
            return {
                "exit_time": None,
                "exit_price": None,
                "exit_type": "time_based_quarter",
                "hold_seconds": 0,
                "status": "not_triggered",
            }

        exit_trade = valid.iloc[-1]
        return {
            "exit_time": exit_trade["datetime"],
            "exit_price": exit_trade["price"],
            "exit_type": "time_based_quarter",
            "hold_seconds": int((exit_trade["datetime"] - entry_time).total_seconds()),
            "status": "filled",
        }

    else:
        raise ValueError(f"Unknown exit_type: {exit_type}")
