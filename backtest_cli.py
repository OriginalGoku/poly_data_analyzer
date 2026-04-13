"""CLI entry point for backtest execution."""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from backtest.backtest_config import DipBuyBacktestConfig
from backtest.backtest_export import export_backtest_results
from backtest.backtest_runner import run_backtest_grid

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Run dip-buy backtest")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--dip-thresholds",
        default="10,15,20",
        help="Comma-separated dip thresholds in cents",
    )
    parser.add_argument(
        "--exit-types",
        default="settlement",
        help="Comma-separated exit types",
    )
    parser.add_argument(
        "--fee-models",
        default="taker",
        help="Comma-separated fee models (taker/maker)",
    )
    parser.add_argument("--sport", default="nba", help="Sport filter (nba/nhl/mlb/all)")
    parser.add_argument("--output", default="backtest_results", help="Output directory")
    parser.add_argument("--data-dir", default="data", help="Data directory")

    args = parser.parse_args()

    # Parse arguments
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    dip_thresholds = tuple(int(x.strip()) for x in args.dip_thresholds.split(","))
    exit_types = [x.strip() for x in args.exit_types.split(",")]
    fee_models = [x.strip() for x in args.fee_models.split(",")]

    # Build configs
    configs = []
    for exit_type in exit_types:
        for fee_model in fee_models:
            config = DipBuyBacktestConfig(
                dip_thresholds=dip_thresholds,
                exit_type=exit_type,
                fee_model=fee_model,
                sport_filter=args.sport,
            )
            configs.append(config)

    logger.info(f"Running backtest from {args.start_date} to {args.end_date}")
    logger.info(f"Configs: {len(configs)} (exits: {set(c.exit_type for c in configs)}, fees: {set(c.fee_model for c in configs)})")
    logger.info(f"Data directory: {args.data_dir}")

    # Create dated subfolder for results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output) / timestamp
    logger.info(f"Results will be saved to: {output_dir}/")

    # Run grid with progress bar
    logger.info("Loading universe and running backtests...")
    agg_df, per_game_df = run_backtest_grid(
        start_date=start_date,
        end_date=end_date,
        configs=configs,
        data_dir=args.data_dir,
        verbose=True,
    )

    logger.info(f"\n✓ Completed {len(per_game_df)} games")

    # Log summary stats
    if not per_game_df.empty:
        if "entry_price" in per_game_df.columns:
            games_with_entry = (per_game_df["entry_price"].notna()).sum()
            games_settled = (per_game_df["settlement_occurred"] == True).sum() if "settlement_occurred" in per_game_df.columns else 0
            logger.info(f"  Games with dip entry triggered: {games_with_entry}")
            logger.info(f"  Games with settlement: {games_settled}")
            if games_with_entry > 0:
                logger.info(f"  Mean ROI (with entry): {per_game_df[per_game_df['entry_price'].notna()]['roi_pct'].mean():.2%}")

    logger.info(f"Aggregated results: {len(agg_df)} strategy combinations tested")

    # Export
    export_backtest_results(
        aggregated_df=agg_df,
        per_game_df=per_game_df,
        output_dir=str(output_dir),
    )

    logger.info(f"Results exported to {output_dir}/")


if __name__ == "__main__":
    main()
