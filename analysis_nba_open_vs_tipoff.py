"""Export NBA open-vs-tip-off exploratory analysis to disk."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from nba_analysis import AnalysisFilters, NBAOpenTipoffAnalysisService, GROUPING_OPTIONS
from settings import load_chart_settings

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - optional dependency at runtime
    tqdm = None


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data", help="Path to the data archive")
    parser.add_argument("--settings-path", default="chart_settings.json", help="Path to chart settings JSON")
    parser.add_argument("--price-quality", default="all", choices=["all", "exact", "inferred"])
    parser.add_argument("--start-date", default=None, help="Inclusive start date YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="Inclusive end date YYYY-MM-DD")
    parser.add_argument(
        "--group-by",
        default="open_interpretable_band",
        choices=sorted(GROUPING_OPTIONS.keys()),
        help="Grouping slice for summary tables and charts",
    )
    parser.add_argument("--output-dir", default="analysis_outputs", help="Root directory for exported reports")
    return parser.parse_args()


def configure_logging(run_dir: Path) -> logging.Logger:
    logger = logging.getLogger("nba_open_tipoff_analysis")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(run_dir / "analysis.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


class ExportProgressObserver:
    """Progress reporting for long dataset builds."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._bar = None
        self._last_logged_index = 0
        self._total = 0
        self._prefix = ""

    def child(self, prefix: str) -> "ExportProgressObserver":
        child = ExportProgressObserver(self.logger)
        child._prefix = f"[{prefix}] "
        return child

    def start(self, total: int, description: str):
        self._total = total
        self.logger.info("%s%s (%s games)", self._prefix, description, total)
        if tqdm is not None:
            self._bar = tqdm(total=total, desc=f"{self._prefix}{description}", unit="game")

    def advance(self, index: int, match_id: str, date: str):
        if self._bar is not None:
            self._bar.update(1)
            self._bar.set_postfix_str(f"{date} {match_id}", refresh=False)
            return

        should_log = index == 1 or index == self._total or (index - self._last_logged_index) >= 50
        if should_log:
            self.logger.info("%sProcessed %s/%s games (%s %s)", self._prefix, index, self._total, date, match_id)
            self._last_logged_index = index

    def finish(self, total: int):
        if self._bar is not None:
            remaining = total - self._bar.n
            if remaining > 0:
                self._bar.update(remaining)
            self._bar.close()
            self._bar = None
        self.logger.info("%sFinished dataset build (%s games)", self._prefix, total)


def write_summary_file(run_dir: Path, summary, filters: AnalysisFilters, group_by: str):
    lines = [
        "# NBA Open vs Tip-Off Analysis",
        "",
        f"- Price quality: `{filters.price_quality}`",
        f"- Start date: `{filters.start_date or 'earliest'}`",
        f"- End date: `{filters.end_date or 'latest'}`",
        f"- Group by: `{group_by}`",
        "",
        "## Headline Metrics",
        f"- Games: `{summary.games}`",
        f"- Dropped by open filter: `{summary.dropped_open_filter_games}`",
        f"- Games with outcome: `{summary.outcome_games}`",
        f"- Games with open prediction: `{summary.open_prediction_games}`",
        f"- Games with tip-off prediction: `{summary.tipoff_prediction_games}`",
        f"- Open-to-tipoff swing rate: `{_format_pct(summary.open_to_tipoff_swing_rate)}`",
        f"- Any pregame favorite switch: `{_format_pct(summary.any_pregame_switch_rate)}`",
        f"- Open favorite win rate: `{_format_pct(summary.open_favorite_win_rate)}`",
        f"- Tip-off favorite win rate: `{_format_pct(summary.tipoff_favorite_win_rate)}`",
        f"- Mean absolute move: `{_format_number(summary.mean_abs_move)}`",
        f"- Mean realized volatility: `{_format_number(summary.mean_path_volatility)}`",
        "",
    ]
    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.output_dir) / f"nba_open_tipoff_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    logger = configure_logging(run_dir)
    logger.info("Loading settings from %s", args.settings_path)
    settings = load_chart_settings(args.settings_path)
    service = NBAOpenTipoffAnalysisService(args.data_dir, settings)
    progress = ExportProgressObserver(logger)
    filters = AnalysisFilters(
        price_quality=args.price_quality,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    logger.info("Building dataset")
    prepared = service.prepare_dataset(filters, progress_observer=progress)
    dataset = prepared.dataset
    logger.info(
        "Loaded %s NBA games after dropping %s by the open filter",
        len(dataset),
        prepared.dropped_open_filter_games,
    )
    dataset.to_csv(run_dir / "dataset.csv", index=False)

    summary = service.build_summary(
        dataset,
        dropped_open_filter_games=prepared.dropped_open_filter_games,
    )
    write_summary_file(run_dir, summary, filters, args.group_by)

    grouped = service.build_group_summary(dataset, args.group_by)
    grouped.to_csv(run_dir / "group_summary.csv", index=False)
    service.build_group_summary(dataset, "open_interpretable_band").to_csv(
        run_dir / "open_band_outcome_summary.csv",
        index=False,
    )
    service.build_group_summary(dataset, "tipoff_interpretable_band").to_csv(
        run_dir / "tipoff_band_outcome_summary.csv",
        index=False,
    )
    service.build_group_summary(dataset, "price_quality").to_csv(
        run_dir / "price_quality_outcome_summary.csv",
        index=False,
    )
    service.build_transition_outcome_summary(dataset).to_csv(
        run_dir / "interpretable_transition_outcome_summary.csv",
        index=False,
    )
    service.build_coverage_summary(
        dataset,
        dropped_open_filter_games=prepared.dropped_open_filter_games,
    ).to_csv(run_dir / "coverage_summary.csv", index=False)

    transition = service.build_transition_matrix(dataset, "open_interpretable_band", "tipoff_interpretable_band")
    transition.to_csv(run_dir / "interpretable_transition_matrix.csv")

    logger.info("Building charts")
    figures = service.figure_builder().build_figures(dataset, args.group_by)
    for name, figure in figures.items():
        figure.write_html(run_dir / f"{name}.html")
        logger.info("Wrote chart %s", name)

    logger.info("Analysis complete. Outputs written to %s", run_dir)


def _format_pct(value):
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def _format_number(value):
    if value is None:
        return "N/A"
    return f"{value:.4f}"


if __name__ == "__main__":
    main()
