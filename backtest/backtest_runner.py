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
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Run backtest grid across universe and configs.

    Args:
        start_date: Backtest start date (inclusive)
        end_date: Backtest end date (inclusive)
        configs: List of DipBuyBacktestConfig to test
        data_dir: Data directory root
        verbose: If True, show tqdm progress bars

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
        exclude_inferred_price_quality=True,
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

            # Run single-game backtest
            result = backtest_single_game(
                date=date,
                match_id=match_id,
                config=config,
                data_dir=data_dir,
            )

            if result is not None:
                all_results.append(result)

    per_game_df = pd.DataFrame(all_results) if all_results else pd.DataFrame()

    # Log entry statistics
    if not per_game_df.empty:
        logger.info(f"Universe: {len(per_game_df)} game results generated")
        status_counts = per_game_df["status"].value_counts().to_dict()
        logger.info(f"Status breakdown: {status_counts}")

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
            for exit_type in [config.exit_type]:
                for fee_model in [config.fee_model]:
                    # Filter results for this combo
                    filtered = per_game_df[
                        (per_game_df["dip_threshold"] == dip_threshold)
                        & (per_game_df["exit_type"] == exit_type)
                        & (per_game_df["fee_model"] == fee_model)
                    ]

                    if filtered.empty:
                        aggregated.append({
                            "dip_threshold": dip_threshold,
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
                        trades_settled = filtered[filtered["settlement_occurred"] == True]

                        aggregated.append({
                            "dip_threshold": dip_threshold,
                            "exit_type": exit_type,
                            "fee_model": fee_model,
                            "total_games": len(filtered),
                            "games_with_entry": len(trades_with_entry),
                            "games_settled": len(trades_settled),
                            "total_trades": len(trades_with_entry),
                            "gross_roi_mean": trades_with_entry["roi_pct"].mean() if len(trades_with_entry) > 0 else 0,
                            "net_roi_mean": trades_with_entry["roi_pct"].mean() if len(trades_with_entry) > 0 else 0,
                            "win_rate": (filtered["true_pnl_cents"] > 0).sum() / len(trades_settled) if len(trades_settled) > 0 else 0,
                            "avg_entry_price": trades_with_entry["entry_price"].mean() if len(trades_with_entry) > 0 else 0,
                            "avg_hold_minutes": (trades_with_entry["hold_seconds"].mean() / 60) if len(trades_with_entry) > 0 else 0,
                        })

    aggregated_df = pd.DataFrame(aggregated)
    return aggregated_df, per_game_df
