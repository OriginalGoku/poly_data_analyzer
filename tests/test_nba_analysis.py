"""Tests for the reusable NBA open-vs-tip-off analysis service."""

import gzip
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import render_page
from nba_analysis import AnalysisFilters, NBAOpenTipoffAnalysisService
from pages.nba_open_tipoff_page import _default_date_window
from settings import ChartSettings
from tests.test_app import _flatten_text


def _write_json_gz(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _write_manifest(path: Path, payload: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def test_service_computes_swing_and_pregame_instability(tmp_path):
    date_dir = tmp_path / "2026-04-10"
    manifest = {
        "match_id": "nba-a-b-2026-04-10",
        "sport": "nba",
        "status": "collected",
        "away_team": "A",
        "home_team": "B",
        "outcomes": ["A", "B"],
        "token_ids": ["t1", "t2"],
    }
    _write_manifest(date_dir / "manifest.json", [manifest])
    _write_json_gz(
        date_dir / "nba-a-b-2026-04-10_trades.json.gz",
        {
            "match_id": manifest["match_id"],
            "sport": "nba",
            "price_checkpoints_meta": {"price_quality": "exact"},
            "price_checkpoints": {
                "t1": {
                    "selected_early_price": 0.55,
                    "selected_early_price_source": "clob_open",
                    "last_pregame_trade_price": 0.40,
                },
                "t2": {
                    "selected_early_price": 0.45,
                    "selected_early_price_source": "clob_open",
                    "last_pregame_trade_price": 0.60,
                },
            },
                "trades": [
                    {"timestamp": 1712792400, "asset": "t1", "price": 0.55, "size": 1000, "side": "BUY", "taker": "0x1"},
                    {"timestamp": 1712792460, "asset": "t2", "price": 0.45, "size": 1000, "side": "BUY", "taker": "0x2"},
                    {"timestamp": 1712793000, "asset": "t2", "price": 0.58, "size": 1200, "side": "BUY", "taker": "0x3"},
                    {"timestamp": 1712793060, "asset": "t1", "price": 0.42, "size": 1200, "side": "SELL", "taker": "0x4"},
                    {"timestamp": 1712793360, "asset": "t2", "price": 0.59, "size": 900, "side": "BUY", "taker": "0x5"},
                    {"timestamp": 1712793660, "asset": "t2", "price": 0.60, "size": 900, "side": "BUY", "taker": "0x6"},
                ],
            },
        )
    _write_json_gz(
        date_dir / "nba-a-b-2026-04-10_events.json.gz",
        {
                "events": [
                    {
                        "time_actual": "2024-04-11T00:30:00Z",
                        "team_tricode": "AAA",
                        "event_type": "2pt",
                        "away_score": 2,
                        "home_score": 0,
                }
            ]
        },
    )

    service = NBAOpenTipoffAnalysisService(
        str(tmp_path),
        ChartSettings(pregame_min_cum_vol=0, vol_spike_lookback=2, vol_spike_std=0.5),
    )
    dataset = service.load_dataset(AnalysisFilters())

    assert len(dataset) == 1
    row = dataset.iloc[0]
    assert row["final_winner"] == "A"
    assert bool(row["has_outcome"]) is True
    assert bool(row["open_prediction_available"]) is True
    assert bool(row["tipoff_prediction_available"]) is True
    assert bool(row["open_favorite_won"]) is True
    assert bool(row["tipoff_favorite_won"]) is False
    assert bool(row["favorite_changed_open_to_tipoff"]) is True
    assert row["favorite_switch_count_pregame"] == 1
    assert bool(row["any_favorite_switch_pregame"]) is True
    assert row["favorite_move_signed"] == pytest.approx(0.05)
    assert row["favorite_outcome_group"] == "Open Favorite Reversed by Tip-Off"
    assert row["favorite_price_realized_volatility"] is not None


def test_render_page_includes_new_route_title():
    content = render_page("/nba-open-tipoff-analysis")
    text = " ".join(_flatten_text(content))
    assert "NBA Open vs Tip-Off Analysis" in text
    assert "Grouped Summary" in text
    assert "Methodology" in text
    assert "dropped-game count" in text


def test_default_date_window_uses_last_month():
    start, end = _default_date_window(
        ["2026-02-01", "2026-03-01", "2026-03-15", "2026-04-09"]
    )
    assert start == "2026-03-15"
    assert end == "2026-04-09"


def test_prepare_dataset_reports_games_dropped_by_open_filter(tmp_path):
    date_dir = tmp_path / "2026-04-10"
    entries = []
    for match_id, open_price, tipoff_price in [
        ("nba-keep", 0.56, 0.60),
        ("nba-drop", 0.49, 0.51),
    ]:
        entries.append(
            {
                "match_id": match_id,
                "sport": "nba",
                "status": "collected",
                "away_team": f"{match_id}-A",
                "home_team": f"{match_id}-B",
                "outcomes": [f"{match_id}-A", f"{match_id}-B"],
                "token_ids": [f"{match_id}-a", f"{match_id}-b"],
            }
        )
        _write_json_gz(
            date_dir / f"{match_id}_trades.json.gz",
            {
                "match_id": match_id,
                "sport": "nba",
                "price_checkpoints_meta": {"price_quality": "exact"},
                "price_checkpoints": {
                    f"{match_id}-a": {
                        "selected_early_price": 1 - open_price,
                        "selected_early_price_source": "clob_open",
                        "last_pregame_trade_price": 1 - tipoff_price,
                    },
                    f"{match_id}-b": {
                        "selected_early_price": open_price,
                        "selected_early_price_source": "clob_open",
                        "last_pregame_trade_price": tipoff_price,
                    },
                },
                "trades": [
                    {"timestamp": 1, "asset": f"{match_id}-a", "price": 1 - open_price, "size": 3000},
                    {"timestamp": 2, "asset": f"{match_id}-b", "price": open_price, "size": 3000},
                ],
            },
        )
    _write_manifest(date_dir / "manifest.json", entries)

    service = NBAOpenTipoffAnalysisService(str(tmp_path), ChartSettings(pregame_min_cum_vol=5000))
    prepared = service.prepare_dataset(AnalysisFilters())

    assert prepared.dropped_open_filter_games == 1
    assert list(prepared.dataset["match_id"]) == ["nba-keep"]


def test_summary_and_grouped_outcome_metrics_handle_missing_coverage(tmp_path):
    date_dir = tmp_path / "2026-04-10"
    entries = [
        {
            "match_id": "nba-full",
            "sport": "nba",
            "status": "collected",
            "away_team": "Away",
            "home_team": "Home",
            "outcomes": ["Away", "Home"],
            "token_ids": ["a1", "h1"],
        },
        {
            "match_id": "nba-missing",
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
        date_dir / "nba-full_trades.json.gz",
        {
            "match_id": "nba-full",
            "sport": "nba",
            "price_checkpoints_meta": {"price_quality": "exact"},
            "price_checkpoints": {
                "a1": {
                    "selected_early_price": 0.35,
                    "selected_early_price_source": "clob_open",
                    "last_pregame_trade_price": 0.40,
                },
                "h1": {
                    "selected_early_price": 0.65,
                    "selected_early_price_source": "clob_open",
                    "last_pregame_trade_price": 0.60,
                },
            },
            "trades": [
                {"timestamp": 1, "asset": "a1", "price": 0.35, "size": 3000},
                {"timestamp": 2, "asset": "h1", "price": 0.65, "size": 3000},
            ],
        },
    )
    _write_json_gz(
        date_dir / "nba-full_events.json.gz",
        {
            "events": [
                {"time_actual": "2026-04-10T19:00:00Z", "away_score": 98, "home_score": 100},
            ]
        },
    )
    _write_json_gz(
        date_dir / "nba-missing_trades.json.gz",
        {
            "match_id": "nba-missing",
            "sport": "nba",
            "price_checkpoints_meta": {"price_quality": "inferred"},
            "price_checkpoints": {
                "a2": {
                    "selected_early_price": 0.45,
                    "selected_early_price_source": "first_pregame_trade",
                    "last_pregame_trade_price": None,
                },
                "h2": {
                    "selected_early_price": 0.55,
                    "selected_early_price_source": "first_pregame_trade",
                    "last_pregame_trade_price": None,
                },
            },
            "trades": [
                {"timestamp": 1, "asset": "a2", "price": 0.45, "size": 3000},
                {"timestamp": 2, "asset": "h2", "price": 0.55, "size": 3000},
            ],
        },
    )

    service = NBAOpenTipoffAnalysisService(str(tmp_path), ChartSettings(pregame_min_cum_vol=5000))
    prepared = service.prepare_dataset(AnalysisFilters())
    dataset = prepared.dataset

    assert len(dataset) == 2
    full_row = dataset[dataset["match_id"] == "nba-full"].iloc[0]
    missing_row = dataset[dataset["match_id"] == "nba-missing"].iloc[0]
    assert bool(full_row["open_favorite_won"]) is True
    assert bool(full_row["tipoff_favorite_won"]) is True
    assert full_row["final_winner"] == "Home"
    assert pd.isna(missing_row["final_winner"])
    assert bool(missing_row["has_outcome"]) is False
    assert bool(missing_row["open_prediction_available"]) is False
    assert bool(missing_row["tipoff_prediction_available"]) is False
    assert missing_row["open_favorite_won"] is None
    assert missing_row["tipoff_favorite_won"] is None

    summary = service.build_summary(dataset, dropped_open_filter_games=prepared.dropped_open_filter_games)
    assert summary.games == 2
    assert summary.outcome_games == 1
    assert summary.open_prediction_games == 1
    assert summary.tipoff_prediction_games == 1
    assert summary.open_favorite_win_rate == pytest.approx(1.0)
    assert summary.tipoff_favorite_win_rate == pytest.approx(1.0)

    grouped = service.build_group_summary(dataset, "price_quality")
    exact = grouped[grouped["price_quality"] == "exact"].iloc[0]
    inferred = grouped[grouped["price_quality"] == "inferred"].iloc[0]
    assert exact["outcome_games"] == 1
    assert exact["open_prediction_games"] == 1
    assert exact["tipoff_prediction_games"] == 1
    assert exact["open_favorite_win_rate"] == pytest.approx(1.0)
    assert exact["tipoff_favorite_win_rate"] == pytest.approx(1.0)
    assert inferred["outcome_games"] == 0
    assert inferred["open_prediction_games"] == 0
    assert inferred["tipoff_prediction_games"] == 0
    assert inferred["open_favorite_win_rate"] != inferred["open_favorite_win_rate"]
    assert inferred["tipoff_favorite_win_rate"] != inferred["tipoff_favorite_win_rate"]

    transition = service.build_transition_outcome_summary(dataset)
    assert "open_favorite_win_rate" in transition.columns
    coverage = service.build_coverage_summary(dataset, dropped_open_filter_games=0)
    assert set(coverage["metric"]) >= {
        "filtered_games",
        "outcome_games",
        "missing_outcome_games",
        "open_prediction_games",
        "tipoff_prediction_games",
    }


def test_service_computes_in_game_switch_and_open_favorite_excursion_metrics(tmp_path):
    date_dir = tmp_path / "2026-04-10"
    manifest = {
        "match_id": "nba-ingame-path",
        "sport": "nba",
        "status": "collected",
        "away_team": "Away",
        "home_team": "Home",
        "outcomes": ["Away", "Home"],
        "token_ids": ["a1", "h1"],
    }
    tipoff = pd.Timestamp("2026-04-10T19:00:00Z")
    _write_manifest(date_dir / "manifest.json", [manifest])
    _write_json_gz(
        date_dir / "nba-ingame-path_trades.json.gz",
        {
            "match_id": manifest["match_id"],
            "sport": "nba",
            "price_checkpoints_meta": {"price_quality": "exact"},
            "price_checkpoints": {
                "a1": {
                    "selected_early_price": 0.35,
                    "selected_early_price_source": "clob_open",
                    "last_pregame_trade_price": 0.45,
                },
                "h1": {
                    "selected_early_price": 0.65,
                    "selected_early_price_source": "clob_open",
                    "last_pregame_trade_price": 0.55,
                },
            },
            "trades": [
                {
                    "timestamp": int((tipoff - pd.Timedelta(minutes=20)).timestamp()),
                    "asset": "a1",
                    "price": 0.35,
                    "size": 3000,
                },
                {
                    "timestamp": int((tipoff - pd.Timedelta(minutes=10)).timestamp()),
                    "asset": "h1",
                    "price": 0.65,
                    "size": 3000,
                },
                {
                    "timestamp": int((tipoff + pd.Timedelta(minutes=1)).timestamp()),
                    "asset": "a1",
                    "price": 0.40,
                    "size": 1200,
                },
                {
                    "timestamp": int((tipoff + pd.Timedelta(minutes=6)).timestamp()),
                    "asset": "a1",
                    "price": 0.65,
                    "size": 1200,
                },
                {
                    "timestamp": int((tipoff + pd.Timedelta(minutes=12)).timestamp()),
                    "asset": "a1",
                    "price": 0.58,
                    "size": 1200,
                },
            ],
        },
    )
    _write_json_gz(
        date_dir / "nba-ingame-path_events.json.gz",
        {
            "events": [
                {"time_actual": "2026-04-10T19:00:00Z", "away_score": 0, "home_score": 0},
                {"time_actual": "2026-04-10T21:00:00Z", "away_score": 103, "home_score": 100},
            ]
        },
    )

    service = NBAOpenTipoffAnalysisService(str(tmp_path), ChartSettings(pregame_min_cum_vol=0))
    dataset = service.load_dataset(AnalysisFilters())

    assert len(dataset) == 1
    row = dataset.iloc[0]
    assert row["last_in_game_favorite_team"] == "Away"
    assert bool(row["favorite_changed_open_to_game_end"]) is True
    assert bool(row["any_favorite_switch_ingame"]) is True
    assert row["favorite_switch_count_ingame"] == 1
    assert row["open_favorite_in_game_min_price"] == pytest.approx(0.35)
    assert row["open_favorite_in_game_max_price"] == pytest.approx(0.60)
    assert row["open_favorite_max_adverse_excursion"] == pytest.approx(0.30)
    assert row["open_favorite_max_adverse_excursion_pct"] == pytest.approx(0.30 / 0.65)

    summary = service.build_summary(dataset)
    assert summary.open_to_game_end_switch_rate == pytest.approx(1.0)
    assert summary.any_in_game_switch_rate == pytest.approx(1.0)
    assert summary.mean_open_favorite_in_game_min_price == pytest.approx(0.35)
    assert summary.mean_open_favorite_max_adverse_excursion_pct == pytest.approx(0.30 / 0.65)

    grouped = service.build_group_summary(dataset, "open_interpretable_band")
    first_group = grouped.iloc[0]
    assert first_group["open_to_game_end_switch_rate"] == pytest.approx(1.0)
    assert first_group["any_in_game_switch_rate"] == pytest.approx(1.0)
    assert first_group["mean_open_favorite_in_game_min_price"] == pytest.approx(0.35)
    assert first_group["mean_open_favorite_max_adverse_excursion_pct"] == pytest.approx(0.30 / 0.65)
