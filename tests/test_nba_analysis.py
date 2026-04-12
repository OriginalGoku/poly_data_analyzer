"""Tests for the reusable NBA open-vs-tip-off analysis service."""

import gzip
import json
import sys
from pathlib import Path

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
