"""Backtest grid runner and results aggregation."""
import logging
from datetime import datetime
from typing import List, Tuple

import pandas as pd
from tqdm import tqdm

from backtest.backtest_config import DipBuyBacktestConfig
from backtest.backtest_single_game import backtest_single_game
from backtest.backtest_universe import filter_upper_strong_universe

logger = logging.getLogger(__name__)


def run_backtest_grid(
    start_date: datetime,
    end_date: datetime,
    configs: List[DipBuyBacktestConfig],
    data_dir: str = "data",
    verbose: bool = False,
    pregame_min_cum_vol: float = 5000,
    open_anchor_stat: str = "vwap",
    open_anchor_window_min: int = 5,
    outlier_settings: dict | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Run backtest grid across universe and configs.

    Args:
        start_date: Backtest start date (inclusive)
        end_date: Backtest end date (inclusive)
        configs: List of DipBuyBacktestConfig to test
        data_dir: Data directory root
        verbose: If True, show tqdm progress bars
        pregame_min_cum_vol: Min cumulative pregame volume before anchoring open
        open_anchor_stat: Aggregation method for open price (vwap/median)
        open_anchor_window_min: Window in minutes for open anchor

    Returns:
        Tuple of (aggregated_df, per_game_df)
        - aggregated_df: One row per strategy combo with aggregate stats
        - per_game_df: All individual game results
    """
    # Get universe
    universe = filter_upper_strong_universe(
        start_date=start_date,
        end_date=end_date,
        data_dir=data_dir,
        exclude_inferred_price_quality=False,
        pregame_min_cum_vol=pregame_min_cum_vol,
        open_anchor_stat=open_anchor_stat,
        open_anchor_window_min=open_anchor_window_min,
    )

    all_results = []
    total_combos = len(universe) * len(configs)

    # Create progress iterator
    iterator = tqdm(
        universe,
        desc="Processing games",
        unit="game",
        disable=not verbose,
    ) if verbose else universe

    for date, match_id, sport, open_fav_price, tipoff_fav_price, token_id, can_settle, price_quality in iterator:
        for config in configs:
            # Skip if sport doesn't match filter
            if config.sport_filter != "all" and config.sport_filter != sport:
                continue

            # Run single-game backtest for each dip threshold
            for dip_threshold in config.dip_thresholds:
                single_config = DipBuyBacktestConfig(
                    dip_thresholds=(dip_threshold,),
                    dip_anchor=config.dip_anchor,
                    exit_type=config.exit_type,
                    profit_target=config.profit_target,
                    fee_model=config.fee_model,
                    sport_filter=config.sport_filter,
                    taker_fee_pct=config.taker_fee_pct,
                    maker_fee_pct=config.maker_fee_pct,
                )
                result = backtest_single_game(
                    date=date,
                    match_id=match_id,
                    config=single_config,
                    data_dir=data_dir,
                    pregame_min_cum_vol=pregame_min_cum_vol,
                    open_anchor_stat=open_anchor_stat,
                    open_anchor_window_min=open_anchor_window_min,
                    outlier_settings=outlier_settings,
                )

                if result is not None:
                    all_results.append(result)

    per_game_df = pd.DataFrame(all_results) if all_results else pd.DataFrame()

    # Log entry statistics
    if not per_game_df.empty:
        logger.info(f"Universe: {len(per_game_df)} game results generated")
        status_counts = per_game_df["status"].value_counts().to_dict()
        logger.info(f"Status breakdown: {status_counts}")

        # Log errors if present
        failed = per_game_df[per_game_df["status"] == "failed_to_load"]
        if not failed.empty and "error" in failed.columns:
            error_counts = failed["error"].value_counts()
            logger.error(f"Load failures (top 3):")
            for error, count in error_counts.head(3).items():
                logger.error(f"  {count}x: {error}")

        if "entry_price" in per_game_df.columns:
            games_with_entry = (per_game_df["entry_price"].notna()).sum()
            logger.info(f"Games with dip entry triggered: {games_with_entry}/{len(per_game_df)}")

            if games_with_entry > 0:
                entry_trades = per_game_df[per_game_df["entry_price"].notna()]
                logger.info(f"  Entry ROI range: {entry_trades['roi_pct'].min():.2%} to {entry_trades['roi_pct'].max():.2%}")
                logger.info(f"  Entry ROI mean: {entry_trades['roi_pct'].mean():.2%}")

    # Aggregate by strategy
    aggregated = []
    if per_game_df.empty:
        # Return empty aggregated results if no games were tested
        logger.warning("No games tested - per_game_df is empty")
        return pd.DataFrame(), per_game_df

    configs_iter = tqdm(
        configs,
        desc="Aggregating results",
        unit="config",
        disable=not verbose,
    ) if verbose else configs

    for config in configs_iter:
        for dip_threshold in config.dip_thresholds:
            dip_anchor = config.dip_anchor
            for exit_type in [config.exit_type]:
                for fee_model in [config.fee_model]:
                    # Filter results for this combo
                    anchor_filter = (
                        (per_game_df["dip_anchor"] == dip_anchor)
                        if "dip_anchor" in per_game_df.columns
                        else True
                    )
                    filtered = per_game_df[
                        (per_game_df["dip_threshold"] == dip_threshold)
                        & (per_game_df["exit_type"] == exit_type)
                        & (per_game_df["fee_model"] == fee_model)
                        & anchor_filter
                    ]

                    if filtered.empty:
                        aggregated.append({
                            "dip_threshold": dip_threshold,
                            "dip_anchor": dip_anchor,
                            "exit_type": exit_type,
                            "fee_model": fee_model,
                            "total_games": 0,
                            "games_with_entry": 0,
                            "games_settled": 0,
                            "total_trades": 0,
                            "gross_roi_mean": 0,
                            "net_roi_mean": 0,
                            "win_rate": 0,
                            "avg_entry_price": 0,
                            "avg_hold_minutes": 0,
                        })
                    else:
                        trades_with_entry = filtered[filtered["entry_price"].notna()]
                        trades_settled = (
                            filtered[filtered["settlement_occurred"] == True]
                            if "settlement_occurred" in filtered.columns
                            else filtered[0:0]  # Empty dataframe
                        )

                        aggregated.append({
                            "dip_threshold": dip_threshold,
                            "dip_anchor": dip_anchor,
                            "exit_type": exit_type,
                            "fee_model": fee_model,
                            "total_games": len(filtered),
                            "games_with_entry": len(trades_with_entry),
                            "games_settled": len(trades_settled),
                            "total_trades": len(trades_with_entry),
                            "gross_roi_mean": (
                                (trades_with_entry["gross_pnl_cents"] / (trades_with_entry["entry_price"] * 100)).mean()
                                if len(trades_with_entry) > 0 else 0
                            ),
                            "net_roi_mean": trades_with_entry["roi_pct"].mean() if len(trades_with_entry) > 0 else 0,
                            "win_rate": (
                                (filtered["true_pnl_cents"] > 0).sum() / len(trades_settled)
                                if "true_pnl_cents" in filtered.columns and len(trades_settled) > 0
                                else 0
                            ),
                            "avg_entry_price": trades_with_entry["entry_price"].mean() if len(trades_with_entry) > 0 else 0,
                            "avg_hold_minutes": (trades_with_entry["hold_seconds"].mean() / 60) if len(trades_with_entry) > 0 else 0,
                            "avg_max_drawdown_cents": (trades_with_entry["max_drawdown_cents"].mean() if "max_drawdown_cents" in trades_with_entry.columns and len(trades_with_entry) > 0 else 0),
                        })

    aggregated_df = pd.DataFrame(aggregated)
    return aggregated_df, per_game_df
