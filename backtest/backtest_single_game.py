"""Single-game backtest execution engine."""
import logging
from datetime import datetime
from typing import Dict, Optional

import pandas as pd

from analytics import get_analytics_view

logger = logging.getLogger(__name__)
from backtest.backtest_baselines import (
    baseline_buy_at_open,
    baseline_buy_at_tipoff,
    baseline_buy_first_ingame,
)
from backtest.backtest_config import DipBuyBacktestConfig
from backtest.backtest_pnl import compute_trade_pnl
from backtest.backtest_settlement import resolve_settlement
from backtest.dip_entry_detection import find_dip_entry, find_exit
from loaders import load_game


def backtest_single_game(
    date: str,
    match_id: str,
    config: DipBuyBacktestConfig,
    data_dir: str = "data",
) -> Optional[Dict]:
    """Run backtest for single game.

    Args:
        date: Game date (YYYY-MM-DD format)
        match_id: Match ID
        config: DipBuyBacktestConfig with strategy parameters
        data_dir: Data directory root

    Returns:
        Single-row dict with all backtest metrics, or None if game failed to load.
    """
    # Load game data
    try:
        game_data = load_game(date, match_id, data_dir=data_dir)
        trades_df = game_data["trades"]
        events = game_data["events"]
        manifest = game_data["manifest"]
    except Exception as e:
        logger.error(f"{date} {match_id}: Failed to load game data: {type(e).__name__}: {str(e)}")
        return {
            "strategy": "dip_buy",
            "dip_threshold": None,
            "exit_type": config.exit_type,
            "fee_model": config.fee_model,
            "sport": None,
            "match_id": match_id,
            "date": date,
            "entry_price": None,
            "exit_price": None,
            "gross_pnl_cents": 0,
            "net_pnl_cents": 0,
            "roi_pct": 0,
            "hold_seconds": 0,
            "status": "failed_to_load",
            "error": str(e),
        }

    sport = manifest.get("sport", "unknown")

    # Get analytics view for open/tipoff prices
    try:
        analytics_view = get_analytics_view(date, data_dir=data_dir)
        game_row = analytics_view[analytics_view["match_id"] == match_id]

        if game_row.empty:
            return {
                "strategy": "dip_buy",
                "dip_threshold": None,
                "exit_type": config.exit_type,
                "fee_model": config.fee_model,
                "sport": sport,
                "match_id": match_id,
                "date": date,
                "status": "missing_analytics",
            }

        game_row = game_row.iloc[0]
        open_price = game_row.get("open_favorite_price")
        tipoff_price = game_row.get("tipoff_favorite_price", open_price)

        if open_price is None or open_price <= 0:
            return {
                "strategy": "dip_buy",
                "dip_threshold": None,
                "exit_type": config.exit_type,
                "fee_model": config.fee_model,
                "sport": sport,
                "match_id": match_id,
                "date": date,
                "status": "missing_open_price",
            }
    except Exception as e:
        return {
            "strategy": "dip_buy",
            "dip_threshold": None,
            "exit_type": config.exit_type,
            "fee_model": config.fee_model,
            "sport": sport,
            "match_id": match_id,
            "date": date,
            "status": "failed_to_load_analytics",
            "error": str(e),
        }

    # Extract game times
    tipoff_time = manifest.get("gamma_start_time")
    if tipoff_time and isinstance(tipoff_time, str):
        tipoff_time = pd.Timestamp(tipoff_time)

    # Estimate game end from manifest or use tipoff + 3 hours
    game_end = manifest.get("game_close_time")
    if game_end and isinstance(game_end, str):
        game_end = pd.Timestamp(game_end)
    else:
        game_end = tipoff_time + pd.Timedelta(hours=3)

    # Find dip entry
    dip_threshold = config.dip_thresholds[0]  # Use first threshold in config

    # Debug logging
    in_game_trades = trades_df[
        (trades_df["time"] >= tipoff_time) & (trades_df["time"] < game_end)
    ]
    if len(in_game_trades) > 0:
        min_price = in_game_trades["price"].min()
        dip_level = open_price - (dip_threshold / 100.0)
        logger.debug(
            f"{match_id}: open={open_price:.4f}, dip_level={dip_level:.4f}, "
            f"min_trade_price={min_price:.4f}, trades={len(in_game_trades)}"
        )

    entry_result = find_dip_entry(
        trades_df=trades_df,
        open_price=open_price,
        dip_threshold_cents=dip_threshold,
        tipoff_time=tipoff_time,
        game_end=game_end,
        settings=None,
    )

    if entry_result is None:
        return {
            "strategy": "dip_buy",
            "dip_threshold": dip_threshold,
            "exit_type": config.exit_type,
            "fee_model": config.fee_model,
            "sport": sport,
            "match_id": match_id,
            "date": date,
            "entry_price": None,
            "exit_price": None,
            "gross_pnl_cents": 0,
            "net_pnl_cents": 0,
            "roi_pct": 0,
            "hold_seconds": 0,
            "status": "not_triggered",
        }

    # Find exit
    exit_result = find_exit(
        trades_df=trades_df,
        entry_time=entry_result["entry_time"],
        entry_price=entry_result["entry_price"],
        exit_type=config.exit_type,
        exit_param=config.profit_target,
        open_price=open_price,
        tipoff_time=tipoff_time,
        game_end=game_end,
        sport=sport,
        settings=None,
    )

    # Resolve settlement
    settlement = resolve_settlement(
        manifest=manifest,
        events=events,
        trades_df=trades_df,
        game_end=game_end,
        sport=sport,
        settings=None,
    )

    # Compute PnL
    pnl = compute_trade_pnl(
        entry=entry_result,
        exit_=exit_result,
        settlement=settlement,
        fee_model=config.fee_model,
        fee_pct=config.fee_pct,
        settings=None,
    )

    # Compute baselines
    baseline_open = baseline_buy_at_open(
        open_price=open_price,
        trades_df=trades_df,
        tipoff_time=tipoff_time,
        game_end=game_end,
        manifest=manifest,
        events=events,
        sport=sport,
        fee_pct=config.fee_pct,
        settings=None,
    )

    baseline_tipoff = baseline_buy_at_tipoff(
        tipoff_price=tipoff_price,
        trades_df=trades_df,
        tipoff_time=tipoff_time,
        game_end=game_end,
        manifest=manifest,
        events=events,
        sport=sport,
        fee_pct=config.fee_pct,
        settings=None,
    )

    baseline_first = baseline_buy_first_ingame(
        trades_df=trades_df,
        tipoff_time=tipoff_time,
        game_end=game_end,
        manifest=manifest,
        events=events,
        sport=sport,
        fee_pct=config.fee_pct,
        settings=None,
    )

    return {
        "strategy": "dip_buy",
        "dip_threshold": dip_threshold,
        "exit_type": config.exit_type,
        "fee_model": config.fee_model,
        "sport": sport,
        "match_id": match_id,
        "date": date,
        "entry_price": pnl["entry_price"],
        "exit_price": pnl["exit_price"],
        "gross_pnl_cents": pnl["gross_pnl_cents"],
        "net_pnl_cents": pnl["net_pnl_cents"],
        "roi_pct": pnl["roi_pct"],
        "hold_seconds": pnl["hold_seconds"],
        "settlement_method": pnl["settlement_method"],
        "settlement_occurred": pnl["settlement_occurred"],
        "true_pnl_cents": pnl["true_pnl_cents"],
        "baseline_buy_at_open_roi": baseline_open.get("roi_pct", 0),
        "baseline_buy_at_tip_roi": baseline_tipoff.get("roi_pct", 0),
        "baseline_buy_first_ingame_roi": baseline_first.get("roi_pct", 0),
        "status": exit_result.get("status", "unknown"),
    }
