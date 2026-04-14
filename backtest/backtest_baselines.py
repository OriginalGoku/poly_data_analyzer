"""Baseline strategy implementations for backtest comparison."""
from typing import Dict, Optional

import pandas as pd

from backtest.backtest_pnl import compute_trade_pnl
from backtest.backtest_settlement import resolve_settlement


def baseline_buy_at_open(
    open_price: float,
    trades_df: pd.DataFrame,
    tipoff_time,
    game_end,
    manifest: Dict,
    events: pd.DataFrame,
    sport: str,
    fee_pct: float,
    settings,
    open_favorite_team: str = None,
) -> Dict:
    """Baseline: buy at open, hold to settlement.

    Args:
        open_price: Entry price at open
        trades_df: In-game trades
        tipoff_time: Game start time
        game_end: Game end time
        manifest: Game manifest
        events: Game events
        sport: Sport code
        fee_pct: Fee percentage
        settings: ChartSettings instance

    Returns:
        PnL dict from compute_trade_pnl()
    """
    if trades_df.empty:
        return {
            "entry_price": open_price,
            "exit_price": None,
            "gross_pnl_cents": 0,
            "net_pnl_cents": 0,
            "roi_pct": 0,
            "hold_seconds": 0,
            "fee_cost_cents": 0,
            "settlement_method": None,
            "settlement_occurred": False,
            "true_pnl_cents": None,
        }

    # Find last in-game trade (settlement)
    in_game = trades_df[
        (trades_df["datetime"] >= tipoff_time) & (trades_df["datetime"] < game_end)
    ]

    if in_game.empty:
        exit_trade = None
    else:
        exit_trade = in_game.iloc[-1]

    entry = {"entry_price": open_price, "entry_time": None}

    if exit_trade is not None:
        exit_ = {
            "exit_price": exit_trade["price"],
            "exit_time": exit_trade["datetime"],
            "hold_seconds": int((exit_trade["datetime"] - tipoff_time).total_seconds()),
        }
    else:
        exit_ = {
            "exit_price": None,
            "exit_time": None,
            "hold_seconds": 0,
        }

    settlement = resolve_settlement(
        manifest, events, trades_df, game_end, sport, settings,
        open_favorite_team=open_favorite_team,
    )

    return compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model="taker",
        fee_pct=fee_pct,
        settings=settings,
    )


def baseline_buy_at_tipoff(
    tipoff_price: float,
    trades_df: pd.DataFrame,
    tipoff_time,
    game_end,
    manifest: Dict,
    events: pd.DataFrame,
    sport: str,
    fee_pct: float,
    settings,
    open_favorite_team: str = None,
) -> Dict:
    """Baseline: buy at tipoff, hold to settlement.

    Args:
        tipoff_price: Entry price at tipoff
        trades_df: In-game trades
        tipoff_time: Game start time
        game_end: Game end time
        manifest: Game manifest
        events: Game events
        sport: Sport code
        fee_pct: Fee percentage
        settings: ChartSettings instance

    Returns:
        PnL dict from compute_trade_pnl()
    """
    if trades_df.empty:
        return {
            "entry_price": tipoff_price,
            "exit_price": None,
            "gross_pnl_cents": 0,
            "net_pnl_cents": 0,
            "roi_pct": 0,
            "hold_seconds": 0,
            "fee_cost_cents": 0,
            "settlement_method": None,
            "settlement_occurred": False,
            "true_pnl_cents": None,
        }

    # Find last in-game trade (settlement)
    in_game = trades_df[
        (trades_df["datetime"] >= tipoff_time) & (trades_df["datetime"] < game_end)
    ]

    if in_game.empty:
        exit_trade = None
    else:
        exit_trade = in_game.iloc[-1]

    entry = {"entry_price": tipoff_price, "entry_time": tipoff_time}

    if exit_trade is not None:
        exit_ = {
            "exit_price": exit_trade["price"],
            "exit_time": exit_trade["datetime"],
            "hold_seconds": int((exit_trade["datetime"] - tipoff_time).total_seconds()),
        }
    else:
        exit_ = {
            "exit_price": None,
            "exit_time": None,
            "hold_seconds": 0,
        }

    settlement = resolve_settlement(
        manifest, events, trades_df, game_end, sport, settings,
        open_favorite_team=open_favorite_team,
    )

    return compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model="taker",
        fee_pct=fee_pct,
        settings=settings,
    )


def baseline_buy_first_ingame(
    trades_df: pd.DataFrame,
    tipoff_time,
    game_end,
    manifest: Dict,
    events: pd.DataFrame,
    sport: str,
    fee_pct: float,
    settings,
    open_favorite_team: str = None,
) -> Dict:
    """Baseline: buy at first in-game trade, hold to settlement.

    Args:
        trades_df: In-game trades
        tipoff_time: Game start time
        game_end: Game end time
        manifest: Game manifest
        events: Game events
        sport: Sport code
        fee_pct: Fee percentage
        settings: ChartSettings instance

    Returns:
        PnL dict from compute_trade_pnl()
    """
    if trades_df.empty:
        return {
            "entry_price": None,
            "exit_price": None,
            "gross_pnl_cents": 0,
            "net_pnl_cents": 0,
            "roi_pct": 0,
            "hold_seconds": 0,
            "fee_cost_cents": 0,
            "settlement_method": None,
            "settlement_occurred": False,
            "true_pnl_cents": None,
        }

    # Find first in-game trade
    in_game = trades_df[
        (trades_df["datetime"] >= tipoff_time) & (trades_df["datetime"] < game_end)
    ]

    if in_game.empty:
        return {
            "entry_price": None,
            "exit_price": None,
            "gross_pnl_cents": 0,
            "net_pnl_cents": 0,
            "roi_pct": 0,
            "hold_seconds": 0,
            "fee_cost_cents": 0,
            "settlement_method": None,
            "settlement_occurred": False,
            "true_pnl_cents": None,
        }

    entry_trade = in_game.iloc[0]
    exit_trade = in_game.iloc[-1]

    entry = {"entry_price": entry_trade["price"], "entry_time": entry_trade["datetime"]}

    exit_ = {
        "exit_price": exit_trade["price"],
        "exit_time": exit_trade["datetime"],
        "hold_seconds": int((exit_trade["datetime"] - entry_trade["datetime"]).total_seconds()),
    }

    settlement = resolve_settlement(
        manifest, events, trades_df, game_end, sport, settings,
        open_favorite_team=open_favorite_team,
    )

    return compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model="taker",
        fee_pct=fee_pct,
        settings=settings,
    )
