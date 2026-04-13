"""Tests for the NBA open-vs-tip-off export script."""

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis_nba_open_vs_tipoff import main, write_summary_file
from nba_analysis import AnalysisFilters, NBAOpenTipoffSummary


def _write_json_gz(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _write_manifest(path: Path, payload: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def test_write_summary_file_includes_outcome_metrics(tmp_path):
    summary = NBAOpenTipoffSummary(
        games=10,
        dropped_open_filter_games=2,
        outcome_games=8,
        open_prediction_games=8,
        tipoff_prediction_games=7,
        open_to_tipoff_swing_rate=0.25,
        any_pregame_switch_rate=0.4,
        open_to_game_end_switch_rate=0.35,
        any_in_game_switch_rate=0.55,
        open_favorite_win_rate=0.625,
        tipoff_favorite_win_rate=0.7142857,
        mean_open_favorite_in_game_min_price=0.41,
        mean_open_favorite_max_adverse_excursion=0.14,
        mean_open_favorite_max_adverse_excursion_pct=0.22,
        mean_abs_move=0.08,
        mean_path_volatility=0.04,
    )

    write_summary_file(tmp_path, summary, AnalysisFilters(price_quality="all"), "open_interpretable_band")
    content = (tmp_path / "summary.md").read_text(encoding="utf-8")

    assert "Games with outcome" in content
    assert "Games with open prediction" in content
    assert "Games with tip-off prediction" in content
    assert "Open favorite win rate" in content
    assert "Tip-off favorite win rate" in content
    assert "Open-to-game-end switch rate" in content
    assert "Any in-game favorite switch" in content
    assert "Mean open-favorite max adverse excursion %" in content


def test_main_writes_outcome_exports(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    date_dir = data_dir / "2026-04-10"
    entries = [
        {
            "match_id": "nba-export-1",
            "sport": "nba",
            "status": "collected",
            "away_team": "Away",
            "home_team": "Home",
            "outcomes": ["Away", "Home"],
            "token_ids": ["a1", "h1"],
        },
        {
            "match_id": "nba-export-2",
            "sport": "nba",
            "status": "collected",
            "away_team": "Road",
            "home_team": "Host",
            "outcomes": ["Road", "Host"],
            "token_ids": ["a2", "h2"],
        },
    ]
    _write_manifest(date_dir / "manifest.json", entries)
    _write_json_gz(
        date_dir / "nba-export-1_trades.json.gz",
        {
            "match_id": "nba-export-1",
            "sport": "nba",
            "price_checkpoints_meta": {"price_quality": "exact"},
            "price_checkpoints": {
                "a1": {
                    "selected_early_price": 0.40,
                    "selected_early_price_source": "clob_open",
                    "last_pregame_trade_price": 0.45,
                },
                "h1": {
                    "selected_early_price": 0.60,
                    "selected_early_price_source": "clob_open",
                    "last_pregame_trade_price": 0.55,
                },
            },
            "trades": [
                {"timestamp": 1, "asset": "a1", "price": 0.40, "size": 3000},
                {"timestamp": 2, "asset": "h1", "price": 0.60, "size": 3000},
            ],
        },
    )
    _write_json_gz(
        date_dir / "nba-export-1_events.json.gz",
        {
            "events": [
                {"time_actual": "2026-04-10T19:00:00Z", "away_score": 101, "home_score": 103},
            ]
        },
    )
    _write_json_gz(
        date_dir / "nba-export-2_trades.json.gz",
        {
            "match_id": "nba-export-2",
            "sport": "nba",
            "price_checkpoints_meta": {"price_quality": "inferred"},
            "price_checkpoints": {
                "a2": {
                    "selected_early_price": 0.44,
                    "selected_early_price_source": "first_pregame_trade",
                    "last_pregame_trade_price": None,
                },
                "h2": {
                    "selected_early_price": 0.56,
                    "selected_early_price_source": "first_pregame_trade",
                    "last_pregame_trade_price": None,
                },
            },
            "trades": [
                {"timestamp": 1, "asset": "a2", "price": 0.44, "size": 3000},
                {"timestamp": 2, "asset": "h2", "price": 0.56, "size": 3000},
            ],
        },
    )

    output_dir = tmp_path / "outputs"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analysis_nba_open_vs_tipoff.py",
            "--data-dir",
            str(data_dir),
            "--settings-path",
            str(Path(__file__).resolve().parent.parent / "chart_settings.json"),
            "--output-dir",
            str(output_dir),
        ],
    )

    main()

    run_dirs = list(output_dir.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "dataset.csv").exists()
    assert (run_dir / "summary.md").exists()
    assert (run_dir / "coverage_summary.csv").exists()
    assert (run_dir / "open_band_outcome_summary.csv").exists()
    assert (run_dir / "tipoff_band_outcome_summary.csv").exists()
    assert (run_dir / "price_quality_outcome_summary.csv").exists()
    assert (run_dir / "interpretable_transition_outcome_summary.csv").exists()

    dataset_csv = (run_dir / "dataset.csv").read_text(encoding="utf-8")
    assert "final_winner" in dataset_csv
    assert "open_favorite_won" in dataset_csv
    assert "tipoff_favorite_won" in dataset_csv

    coverage_csv = (run_dir / "coverage_summary.csv").read_text(encoding="utf-8")
    assert "outcome_games" in coverage_csv
    assert "tipoff_prediction_games" in coverage_csv

    summary_md = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "Open favorite win rate" in summary_md
    assert "Tip-off favorite win rate" in summary_md
