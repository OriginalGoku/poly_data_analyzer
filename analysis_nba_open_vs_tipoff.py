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
    parser.add_argument(
        "--path-analysis",
        action="store_true",
        help="Run the heavy full-resolution passes (TP×SL bracket + live win-prob model). "
        "Each re-reads every game's trades; skip for fast scalar-only runs.",
    )
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
        f"- Open-to-game-end switch rate: `{_format_pct(summary.open_to_game_end_switch_rate)}`",
        f"- Any in-game favorite switch: `{_format_pct(summary.any_in_game_switch_rate)}`",
        f"- Open favorite win rate: `{_format_pct(summary.open_favorite_win_rate)}`",
        f"- Tip-off favorite win rate: `{_format_pct(summary.tipoff_favorite_win_rate)}`",
        f"- Mean open-favorite in-game min price: `{_format_number(summary.mean_open_favorite_in_game_min_price)}`",
        f"- Mean open-favorite max adverse excursion: `{_format_number(summary.mean_open_favorite_max_adverse_excursion)}`",
        f"- Mean open-favorite max adverse excursion %: `{_format_pct(summary.mean_open_favorite_max_adverse_excursion_pct)}`",
        f"- Mean absolute move: `{_format_number(summary.mean_abs_move)}`",
        f"- Mean realized volatility: `{_format_number(summary.mean_path_volatility)}`",
        "",
    ]
    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def append_stop_loss_ev_section(run_dir: Path, dataset, ev_grid):
    """Append the argmax-per-band stop-loss EV table to ``summary.md``."""
    missing_outcome = int(dataset["tipoff_favorite_won"].isna().sum()) if "tipoff_favorite_won" in dataset else 0
    lines = ["", "## Stop-Loss EV (per tip-off band)", ""]
    if ev_grid.empty:
        lines.append("_No EV grid rows (insufficient outcome/entry data)._")
    else:
        argmax = ev_grid[ev_grid["is_argmax"]]
        lines.append("| Band | Argmax stop | EV | EV no-stop | Win stopout | Loss stopout | N games |")
        lines.append("|---|---|---|---|---|---|---|")
        for _, row in argmax.iterrows():
            lines.append(
                f"| {row['band']} | {_format_number(row['stop_price'])} | "
                f"{_format_number(row['ev_per_unit_stake'])} | {_format_number(row['ev_no_stop_reference'])} | "
                f"{_format_pct(row['win_stopout_rate'])} | {_format_pct(row['loss_stopout_rate'])} | "
                f"{int(row['n_games'])} |"
            )
    lines += [
        "",
        f"- Games excluded from EV (null tip-off outcome): `{missing_outcome}`",
        "- _In-game min is from a 5-minute resample; a stop touched between bars "
        "may be missed, so EV is an upper-bound estimate._",
        "",
    ]
    with open(run_dir / "summary.md", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def append_take_profit_ev_section(run_dir: Path, tp_grid):
    """Append the argmax-per-band take-profit EV table to ``summary.md``."""
    lines = ["", "## Take-Profit EV (per tip-off band, no stop)", ""]
    if tp_grid.empty:
        lines.append("_No TP grid rows (insufficient outcome/entry data)._")
    else:
        argmax = tp_grid[tp_grid["is_argmax"]]
        lines.append("| Band | Argmax target | EV | EV no-TP | Win TP hit | Loss TP hit | N games |")
        lines.append("|---|---|---|---|---|---|---|")
        for _, row in argmax.iterrows():
            lines.append(
                f"| {row['band']} | {_format_number(row['target_price'])} | "
                f"{_format_number(row['ev_per_unit_stake'])} | {_format_number(row['ev_no_tp_reference'])} | "
                f"{_format_pct(row['win_tp_rate'])} | {_format_pct(row['loss_tp_rate'])} | "
                f"{int(row['n_games'])} |"
            )
    lines += [
        "",
        "- _Take-profit modelled as a limit sell (fills at target, no slippage); "
        "single-barrier only — see the backtest engine for TP+SL brackets._",
        "",
    ]
    with open(run_dir / "summary.md", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def append_oos_section(run_dir: Path, oos):
    """Append the stop-loss out-of-sample (train/test) validation to ``summary.md``."""
    lines = ["", "## Stop-Loss Out-of-Sample Validation (chronological 70/30)", ""]
    if oos.empty:
        lines.append("_Insufficient data for a train/test split._")
    else:
        lines.append(
            "| Band | Train stop | Train EV | Test EV @ stop | Test no-stop | Overfit gap | Beats no-stop? | N train/test |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for _, row in oos.iterrows():
            lines.append(
                f"| {row['band']} | {_format_number(row['train_argmax_stop'])} | "
                f"{_format_number(row['train_ev'])} | {_format_number(row['test_ev_at_train_stop'])} | "
                f"{_format_number(row['test_no_stop_ev'])} | {_format_number(row['overfit_gap'])} | "
                f"{'YES' if row['test_beats_no_stop'] else 'no'} | "
                f"{int(row['n_train'])}/{int(row['n_test'])} |"
            )
    lines += [
        "",
        "- _Stop chosen on the earliest 70% of games, evaluated on the later 30%. "
        "A real edge keeps `Test EV @ stop` > `Test no-stop`; a large overfit gap = winner's curse._",
        "",
    ]
    with open(run_dir / "summary.md", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def append_robustness_section(run_dir: Path, walk_forward, bootstrap):
    """Append walk-forward + bootstrap-CI robustness tables to ``summary.md``."""
    lines = ["", "## Stop-Loss Robustness (walk-forward + bootstrap)", ""]
    if walk_forward.empty:
        lines.append("_Insufficient data for walk-forward folds._")
    else:
        lines.append("### Walk-forward (expanding folds)")
        lines.append("| Band | Folds | Mean test EV | Std | Folds +EV | Folds beat no-stop | Mean stop |")
        lines.append("|---|---|---|---|---|---|---|")
        for _, r in walk_forward.iterrows():
            lines.append(
                f"| {r['band']} | {int(r['n_folds'])} | {_format_number(r['mean_test_ev'])} | "
                f"{_format_number(r['std_test_ev'])} | {int(r['folds_positive'])}/{int(r['n_folds'])} | "
                f"{int(r['folds_beat_no_stop'])}/{int(r['n_folds'])} | {_format_number(r['mean_train_stop'])} |"
            )
    lines.append("")
    if not bootstrap.empty:
        lines.append("### Bootstrap 95% CI on EV at full-sample argmax stop")
        lines.append("| Band | Stop | EV | 95% CI | P(EV>0) | t-stat | Mean ROI % | EV no-stop | N |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for _, r in bootstrap.iterrows():
            lines.append(
                f"| {r['band']} | {_format_number(r['argmax_stop'])} | {_format_number(r['ev_per_unit_stake'])} | "
                f"[{_format_number(r['ev_ci_low'])}, {_format_number(r['ev_ci_high'])}] | "
                f"{_format_pct(r['prob_ev_positive'])} | {r['t_stat']:.2f} | "
                f"{_format_number(r['mean_roi_pct'])}% | {_format_number(r['ev_no_stop'])} | {int(r['n_games'])} |"
            )
    lines += [
        "",
        "- _Walk-forward re-selects the stop on each train slice (overfit-honest). "
        "Bootstrap CI excluding 0 + P(EV>0) near 1 = a statistically real edge._",
        "",
    ]
    with open(run_dir / "summary.md", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def append_winprob_section(run_dir: Path, win_table, mispricing, n_train, n_test):
    """Append the live win-prob mispricing test (Lever 3) to ``summary.md``."""
    lines = ["", "## Live Win-Probability Mispricing Test (Lever 3)", ""]
    lines.append(
        f"Win-prob table fit on {n_train} train games (chronological); mispricing "
        f"measured on {n_test} held-out test games."
    )
    lines.append("")
    if mispricing.empty:
        lines.append("_Insufficient data for the win-prob mispricing test._")
    else:
        lines.append(
            "Buy favorite when model says it is underpriced by `edge = model_prob - market_price`; "
            "hold to settlement. Positive EV in the high-edge buckets = tradeable mispricing."
        )
        lines.append("")
        lines.append("| Edge bucket | N | Realized win rate | Mean market price | Mean model prob | EV |")
        lines.append("|---|---|---|---|---|---|")
        for _, r in mispricing.iterrows():
            lines.append(
                f"| {r['edge_bucket']} | {int(r['n'])} | {_format_pct(r['realized_win_rate'])} | "
                f"{_format_number(r['mean_market_price'])} | {_format_number(r['mean_model_prob'])} | "
                f"{_format_number(r['ev_per_unit_stake'])} |"
            )
    lines += [
        "",
        "- _Model = empirical P(win | game-time bucket, favorite-lead bucket) from train games. "
        "Out-of-sample by construction (train/test split)._",
        "",
    ]
    with open(run_dir / "summary.md", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def append_bracket_ev_section(run_dir: Path, bracket):
    """Append the argmax-per-band TP+SL bracket table to ``summary.md``."""
    lines = ["", "## Bracket EV (per tip-off band, TP + SL, first-passage)", ""]
    if bracket.empty:
        lines.append("_No bracket grid rows (insufficient outcome/entry/path data)._")
    else:
        argmax = bracket[bracket["is_argmax"]]
        lines.append(
            "| Band | Stop | Target | EV | EV no-bracket | TP exit | SL exit | Settle | N games |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for _, row in argmax.iterrows():
            lines.append(
                f"| {row['band']} | {_format_number(row['stop_price'])} | "
                f"{_format_number(row['target_price'])} | {_format_number(row['ev_per_unit_stake'])} | "
                f"{_format_number(row['ev_no_bracket_reference'])} | "
                f"{_format_pct(row['tp_exit_rate'])} | {_format_pct(row['sl_exit_rate'])} | "
                f"{_format_pct(row['settle_rate'])} | {int(row['n_games'])} |"
            )
    lines += [
        "",
        "- _Bracket resolved by full-resolution first-passage on the favorite-side "
        "trade path (TP before SL matters); TP is a limit sell, SL a market order._",
        "",
    ]
    with open(run_dir / "summary.md", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


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

    distribution = service.build_band_outcome_distribution(dataset)
    distribution.to_csv(run_dir / "tipoff_band_min_price_distribution.csv", index=False)

    ev_grid = service.build_band_stop_loss_ev_grid(dataset, settings)
    ev_grid.to_csv(run_dir / "tipoff_band_stop_loss_ev.csv", index=False)
    append_stop_loss_ev_section(run_dir, dataset, ev_grid)

    oos = service.build_stop_loss_oos_validation(dataset, settings)
    oos.to_csv(run_dir / "tipoff_stop_loss_oos_validation.csv", index=False)
    append_oos_section(run_dir, oos)

    from nba_tipoff_robustness import bootstrap_stop_loss_ci, walk_forward_stop_loss

    walk_forward = walk_forward_stop_loss(dataset, settings)
    walk_forward.to_csv(run_dir / "tipoff_stop_loss_walk_forward.csv", index=False)
    bootstrap = bootstrap_stop_loss_ci(dataset, settings)
    bootstrap.to_csv(run_dir / "tipoff_stop_loss_bootstrap_ci.csv", index=False)
    append_robustness_section(run_dir, walk_forward, bootstrap)

    tp_grid = service.build_band_take_profit_ev_grid(dataset, settings)
    tp_grid.to_csv(run_dir / "tipoff_band_take_profit_ev.csv", index=False)
    append_take_profit_ev_section(run_dir, tp_grid)

    if args.path_analysis:
        from nba_tipoff_bracket import build_band_bracket_ev_grid

        logger.info("Building TP x SL bracket grid (full-resolution first-passage)")
        bracket = build_band_bracket_ev_grid(args.data_dir, settings, dataset)
        bracket.to_csv(run_dir / "tipoff_band_bracket_ev.csv", index=False)
        append_bracket_ev_section(run_dir, bracket)

        from nba_tipoff_winprob import build_winprob_analysis

        logger.info("Building live win-probability model + mispricing test (Lever 3)")
        win_table, mispricing, n_tr, n_te = build_winprob_analysis(args.data_dir, settings, dataset)
        win_table.to_csv(run_dir / "winprob_table.csv", index=False)
        mispricing.to_csv(run_dir / "winprob_mispricing_test.csv", index=False)
        append_winprob_section(run_dir, win_table, mispricing, n_tr, n_te)
    else:
        logger.info("Skipping path-analysis passes (bracket + win-prob); pass --path-analysis to enable")

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
