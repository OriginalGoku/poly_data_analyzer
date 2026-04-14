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
    pregame_min_cum_vol: float = 5000,
    open_anchor_stat: str = "vwap",
    open_anchor_window_min: int = 5,
    outlier_settings: dict | None = None,
) -> Optional[Dict]:
    """Run backtest for single game.

    Args:
        date: Game date (YYYY-MM-DD format)
        match_id: Match ID
        config: DipBuyBacktestConfig with strategy parameters
        data_dir: Data directory root
        pregame_min_cum_vol: Min cumulative pregame volume before anchoring open
        open_anchor_stat: Aggregation method for open price (vwap/median)
        open_anchor_window_min: Window in minutes for open anchor

    Returns:
        Single-row dict with all backtest metrics, or None if game failed to load.
    """
    # Load game data
    try:
        game_data = load_game(data_dir, date, match_id, outlier_settings=outlier_settings)
        trades_df = game_data["trades_df"]
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
        analytics_view = get_analytics_view(
            data_dir=data_dir,
            start_date=date,
            end_date=date,
            pregame_min_cum_vol=pregame_min_cum_vol,
            open_anchor_stat=open_anchor_stat,
            open_anchor_window_min=open_anchor_window_min,
        )
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
        open_favorite_team = game_row.get("open_favorite_team")

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

    # Filter trades to favorite token only
    fav_trades_df = trades_df
    if open_favorite_team and "team" in trades_df.columns:
        fav_trades_df = trades_df[trades_df["team"] == open_favorite_team].copy()
        if fav_trades_df.empty:
            logger.warning(f"{match_id}: No trades for favorite team '{open_favorite_team}'")

    # Select anchor price based on config
    dip_threshold = config.dip_thresholds[0]  # Use first threshold in config
    dip_anchor = config.dip_anchor
    anchor_price = tipoff_price if dip_anchor == "tipoff" else open_price

    if dip_anchor == "tipoff" and (tipoff_price is None or tipoff_price <= 0):
        return {
            "strategy": "dip_buy",
            "dip_threshold": dip_threshold,
            "dip_anchor": dip_anchor,
            "exit_type": config.exit_type,
            "fee_model": config.fee_model,
            "sport": sport,
            "match_id": match_id,
            "date": date,
            "status": "missing_tipoff_price",
        }

    # Debug logging
    in_game_trades = fav_trades_df[
        (fav_trades_df["datetime"] >= tipoff_time) & (fav_trades_df["datetime"] < game_end)
    ]
    if len(in_game_trades) > 0:
        min_price = in_game_trades["price"].min()
        dip_level = anchor_price - (dip_threshold / 100.0)
        logger.debug(
            f"{match_id}: anchor={dip_anchor} price={anchor_price:.4f}, dip_level={dip_level:.4f}, "
            f"min_trade_price={min_price:.4f}, trades={len(in_game_trades)}"
        )

    entry_result = find_dip_entry(
        trades_df=fav_trades_df,
        open_price=anchor_price,
        dip_threshold_cents=dip_threshold,
        tipoff_time=tipoff_time,
        game_end=game_end,
        settings=None,
    )

    if entry_result is None:
        return {
            "strategy": "dip_buy",
            "dip_threshold": dip_threshold,
            "dip_anchor": dip_anchor,
            "exit_type": config.exit_type,
            "fee_model": config.fee_model,
            "sport": sport,
            "match_id": match_id,
            "date": date,
            "entry_price": None,
            "entry_time": None,
            "exit_price": None,
            "gross_pnl_cents": 0,
            "net_pnl_cents": 0,
            "roi_pct": 0,
            "hold_seconds": 0,
            "max_drawdown_cents": 0,
            "status": "not_triggered",
        }

    # Find exit
    exit_result = find_exit(
        trades_df=fav_trades_df,
        entry_time=entry_result["entry_time"],
        entry_price=entry_result["entry_price"],
        exit_type=config.exit_type,
        exit_param=config.profit_target,
        open_price=anchor_price,
        tipoff_time=tipoff_time,
        game_end=game_end,
        sport=sport,
        settings=None,
    )

    # Resolve settlement
    settlement = resolve_settlement(
        manifest=manifest,
        events=events,
        trades_df=fav_trades_df,
        game_end=game_end,
        sport=sport,
        settings=None,
        open_favorite_team=open_favorite_team,
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

    # Compute max drawdown after entry
    max_drawdown_cents = 0.0
    entry_price = entry_result["entry_price"]
    entry_time = entry_result["entry_time"]
    dd_end = exit_result.get("exit_time") or game_end
    post_entry_trades = fav_trades_df[
        (fav_trades_df["datetime"] > entry_time)
        & (fav_trades_df["datetime"] <= dd_end)
    ]
    if not post_entry_trades.empty:
        min_price_after = post_entry_trades["price"].min()
        drawdown = entry_price - min_price_after
        max_drawdown_cents = max(0.0, drawdown * 100)

    # Compute baselines
    baseline_open = baseline_buy_at_open(
        open_price=open_price,
        trades_df=fav_trades_df,
        tipoff_time=tipoff_time,
        game_end=game_end,
        manifest=manifest,
        events=events,
        sport=sport,
        fee_pct=config.fee_pct,
        settings=None,
        open_favorite_team=open_favorite_team,
    )

    baseline_tipoff = baseline_buy_at_tipoff(
        tipoff_price=tipoff_price,
        trades_df=fav_trades_df,
        tipoff_time=tipoff_time,
        game_end=game_end,
        manifest=manifest,
        events=events,
        sport=sport,
        fee_pct=config.fee_pct,
        settings=None,
        open_favorite_team=open_favorite_team,
    )

    baseline_first = baseline_buy_first_ingame(
        trades_df=fav_trades_df,
        tipoff_time=tipoff_time,
        game_end=game_end,
        manifest=manifest,
        events=events,
        sport=sport,
        fee_pct=config.fee_pct,
        settings=None,
        open_favorite_team=open_favorite_team,
    )

    return {
        "strategy": "dip_buy",
        "dip_threshold": dip_threshold,
        "dip_anchor": dip_anchor,
        "exit_type": config.exit_type,
        "fee_model": config.fee_model,
        "sport": sport,
        "match_id": match_id,
        "date": date,
        "entry_price": pnl["entry_price"],
        "entry_time": entry_result["entry_time"].isoformat() if entry_result.get("entry_time") else None,
        "exit_price": pnl["exit_price"],
        "gross_pnl_cents": pnl["gross_pnl_cents"],
        "net_pnl_cents": pnl["net_pnl_cents"],
        "roi_pct": pnl["roi_pct"],
        "hold_seconds": pnl["hold_seconds"],
        "settlement_method": pnl["settlement_method"],
        "settlement_occurred": pnl["settlement_occurred"],
        "true_pnl_cents": pnl["true_pnl_cents"],
        "max_drawdown_cents": max_drawdown_cents,
        "baseline_buy_at_open_roi": baseline_open.get("roi_pct", 0),
        "baseline_buy_at_tip_roi": baseline_tipoff.get("roi_pct", 0),
        "baseline_buy_first_ingame_roi": baseline_first.get("roi_pct", 0),
        "status": exit_result.get("status", "unknown"),
    }
