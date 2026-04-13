"""CLI entry point for backtest execution."""
import argparse
from datetime import datetime

from tqdm import tqdm

from backtest_config import DipBuyBacktestConfig
from backtest_export import export_backtest_results
from backtest_runner import run_backtest_grid


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

    print(f"Running backtest from {args.start_date} to {args.end_date}")
    print(f"Configs: {len(configs)}")

    # Run grid with progress bar
    agg_df, per_game_df = run_backtest_grid(
        start_date=start_date,
        end_date=end_date,
        configs=configs,
        data_dir=args.data_dir,
        verbose=True,
    )

    print(f"\n✓ Completed {len(per_game_df)} games")

    # Export
    export_backtest_results(
        aggregated_df=agg_df,
        per_game_df=per_game_df,
        output_dir=args.output,
    )

    print(f"Results exported to {args.output}/")


if __name__ == "__main__":
    main()
