"""CLI entry point for scenario-based backtest execution."""
from __future__ import annotations

import argparse
import fnmatch
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from backtest.backtest_export import export_backtest_results
from backtest.contracts import Scenario
from backtest.runner import run
from backtest.scenarios import load_scenarios
from settings import load_chart_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _select_scenarios(
    available: Dict[str, Scenario],
    names: List[str],
    glob_pattern: str | None,
) -> List[Scenario]:
    if not names and not glob_pattern:
        raise SystemExit("must specify --scenario or --scenarios-glob")

    selected: Dict[str, Scenario] = {}

    if names:
        for requested in names:
            matched = [
                s for s in available.values()
                if s.name == requested or s.name.startswith(f"{requested}__")
            ]
            if not matched:
                raise SystemExit(f"unknown scenario: {requested}")
            for s in matched:
                selected[s.name] = s

    if glob_pattern:
        matched = [s for s in available.values() if fnmatch.fnmatch(s.name, glob_pattern)]
        if not matched:
            raise SystemExit(f"no scenarios match glob: {glob_pattern}")
        for s in matched:
            selected[s.name] = s

    return list(selected.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scenario-based backtest")
    parser.add_argument("--scenario", action="append", default=[],
                        help="Scenario name (repeatable)")
    parser.add_argument("--scenarios-glob", default=None,
                        help="Glob pattern matching scenario names")
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    parser.add_argument("--output", default="backtest_output", help="Output directory")
    parser.add_argument("--scenarios-dir", default="backtest/scenarios",
                        help="Directory of scenario JSON files")
    parser.add_argument("--heatmap-row", default=None,
                        help="Aggregation column for heatmap rows (optional)")
    parser.add_argument("--heatmap-col", default=None,
                        help="Aggregation column for heatmap cols (optional)")
    parser.add_argument("--heatmap-metric", default="mean_roi_pct",
                        help="Aggregation metric column for heatmap")

    args = parser.parse_args()

    try:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    except ValueError as e:
        raise SystemExit(f"invalid date (expected YYYY-MM-DD): {e}")
    if end_date < start_date:
        raise SystemExit(f"--end-date {args.end_date} is before --start-date {args.start_date}")

    available = load_scenarios(args.scenarios_dir)
    if not available:
        raise SystemExit(f"no scenarios found in {args.scenarios_dir}")

    selected = _select_scenarios(available, args.scenario, args.scenarios_glob)
    logger.info("Selected %d scenario(s): %s", len(selected), [s.name for s in selected])

    settings_path = Path(__file__).parent / "chart_settings.json"
    settings = load_chart_settings(settings_path).to_dict() if settings_path.exists() else {}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = f"{args.start_date}_{args.end_date}_{timestamp}"
    output_dir = Path(args.output) / folder
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Results will be saved to %s/", output_dir)

    per_position_df, aggregation_df = run(
        scenarios=selected,
        start_date=start_date,
        end_date=end_date,
        data_dir=args.data_dir,
        settings=settings,
    )

    logger.info("Completed: %d positions, %d aggregated rows",
                len(per_position_df), len(aggregation_df))

    heatmap_dims = (
        (args.heatmap_row, args.heatmap_col)
        if args.heatmap_row and args.heatmap_col
        else None
    )
    export_backtest_results(
        per_position_df=per_position_df,
        aggregation_df=aggregation_df,
        output_path=str(output_dir),
        heatmap_dims=heatmap_dims,
        metric=args.heatmap_metric,
    )
    logger.info("Results exported to %s/", output_dir)


if __name__ == "__main__":
    main()
