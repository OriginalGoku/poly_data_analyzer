"""Tests for game-level regime analytics."""

import gzip
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics import (
    _load_game_analytics_cached,
    build_analysis_summary,
    get_analytics_view,
    get_available_sports,
    load_game_analytics,
)


def _write_trade_file(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _write_manifest(path: Path, entries: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


class TestAnalytics:
    def setup_method(self):
        _load_game_analytics_cached.cache_clear()

    def test_loads_multi_sport_game_records(self, tmp_path):
        date_dir = tmp_path / "2026-04-10"
        manifests = [
            {
                "match_id": "nba-a-b-2026-04-10",
                "sport": "nba",
                "status": "collected",
                "away_team": "A",
                "home_team": "B",
                "outcomes": ["A", "B"],
                "token_ids": ["t1", "t2"],
            },
            {
                "match_id": "nhl-c-d-2026-04-10",
                "sport": "nhl",
                "status": "collected",
                "away_team": "C",
                "home_team": "D",
                "outcomes": ["C", "D"],
                "token_ids": ["u1", "u2"],
            },
        ]
        _write_manifest(date_dir / "manifest.json", manifests)
        _write_trade_file(
            date_dir / "nba-a-b-2026-04-10_trades.json.gz",
            {
                "match_id": manifests[0]["match_id"],
                "sport": "nba",
                "price_checkpoints_meta": {"price_quality": "exact"},
                "price_checkpoints": {
                    "t1": {
                        "selected_early_price": 0.40,
                        "selected_early_price_source": "clob_open",
                        "last_pregame_trade_price": 0.35,
                    },
                    "t2": {
                        "selected_early_price": 0.60,
                        "selected_early_price_source": "clob_open",
                        "last_pregame_trade_price": 0.65,
                    },
                },
                "trades": [
                    {"timestamp": 1, "asset": "t1", "price": 0.40, "size": 3000},
                    {"timestamp": 2, "asset": "t2", "price": 0.60, "size": 3000},
                ],
            },
        )
        _write_trade_file(
            date_dir / "nhl-c-d-2026-04-10_trades.json.gz",
            {
                "match_id": manifests[1]["match_id"],
                "sport": "nhl",
                "price_checkpoints_meta": {"price_quality": "inferred"},
                "price_checkpoints": {
                    "u1": {
                        "selected_early_price": 0.52,
                        "selected_early_price_source": "first_pregame_trade",
                        "last_pregame_trade_price": 0.55,
                    },
                    "u2": {
                        "selected_early_price": 0.48,
                        "selected_early_price_source": "first_pregame_trade",
                        "last_pregame_trade_price": 0.45,
                    },
                },
                "trades": [
                    {"timestamp": 1, "asset": "u1", "price": 0.52, "size": 3000},
                    {"timestamp": 2, "asset": "u2", "price": 0.48, "size": 3000},
                ],
            },
        )

        df = load_game_analytics(str(tmp_path), pregame_min_cum_vol=5000)

        assert set(df["sport"]) == {"nba", "nhl"}
        nba = df[df["match_id"] == "nba-a-b-2026-04-10"].iloc[0]
        assert nba["open_favorite_team"] == "B"
        assert nba["open_favorite_price"] == 0.60
        assert nba["tipoff_favorite_team"] == "B"
        assert nba["tipoff_favorite_price"] == 0.65
        assert nba["open_interpretable_band"] == "Lower Moderate"
        assert nba["tipoff_interpretable_band"] == "Upper Moderate"

    def test_get_analytics_view_applies_quality_filter_and_quantile_bands(self, tmp_path):
        date_dir = tmp_path / "2026-04-10"
        entries = []
        for idx, (match_id, quality, open_price, tipoff_price) in enumerate(
            [
                ("nba-1", "exact", 0.51, 0.52),
                ("nba-2", "exact", 0.60, 0.66),
                ("nba-3", "exact", 0.88, 0.90),
                ("nba-4", "inferred", 0.54, 0.57),
            ],
            start=1,
        ):
            entries.append(
                {
                    "match_id": match_id,
                    "sport": "nba",
                    "status": "collected",
                    "away_team": f"A{idx}",
                    "home_team": f"B{idx}",
                    "outcomes": [f"A{idx}", f"B{idx}"],
                    "token_ids": [f"t{idx}a", f"t{idx}b"],
                }
            )
            _write_trade_file(
                date_dir / f"{match_id}_trades.json.gz",
                {
                    "match_id": match_id,
                    "sport": "nba",
                    "price_checkpoints_meta": {"price_quality": quality},
                    "price_checkpoints": {
                        f"t{idx}a": {
                            "selected_early_price": 1 - open_price,
                            "selected_early_price_source": "clob_open",
                            "last_pregame_trade_price": 1 - tipoff_price,
                        },
                        f"t{idx}b": {
                            "selected_early_price": open_price,
                            "selected_early_price_source": "clob_open",
                            "last_pregame_trade_price": tipoff_price,
                        },
                    },
                    "trades": [
                        {"timestamp": 1, "asset": f"t{idx}a", "price": 1 - open_price, "size": 3000},
                        {"timestamp": 2, "asset": f"t{idx}b", "price": open_price, "size": 3000},
                    ],
                },
            )
        _write_manifest(date_dir / "manifest.json", entries)

        exact_view = get_analytics_view(
            str(tmp_path),
            sport="nba",
            price_quality_filter="exact",
            pregame_min_cum_vol=5000,
        )

        assert len(exact_view) == 3
        assert set(exact_view["price_quality"]) == {"exact"}
        assert set(exact_view["open_quantile_band"]) == {"Q1", "Q2", "Q3"}

    def test_build_analysis_summary_uses_filtered_population(self, tmp_path):
        date_dir = tmp_path / "2026-04-10"
        entries = []
        for idx, price in enumerate([0.52, 0.60, 0.84], start=1):
            entries.append(
                {
                    "match_id": f"mlb-{idx}",
                    "sport": "mlb",
                    "status": "collected",
                    "away_team": f"Away{idx}",
                    "home_team": f"Home{idx}",
                    "outcomes": [f"Away{idx}", f"Home{idx}"],
                    "token_ids": [f"m{idx}a", f"m{idx}b"],
                }
            )
            _write_trade_file(
                date_dir / f"mlb-{idx}_trades.json.gz",
                {
                    "match_id": f"mlb-{idx}",
                    "sport": "mlb",
                    "price_checkpoints_meta": {"price_quality": "exact"},
                    "price_checkpoints": {
                        f"m{idx}a": {
                            "selected_early_price": 1 - price,
                            "selected_early_price_source": "clob_open",
                            "last_pregame_trade_price": 1 - price,
                        },
                        f"m{idx}b": {
                            "selected_early_price": price,
                            "selected_early_price_source": "clob_open",
                            "last_pregame_trade_price": price,
                        },
                    },
                    "trades": [
                        {"timestamp": 1, "asset": f"m{idx}a", "price": 1 - price, "size": 3000},
                        {"timestamp": 2, "asset": f"m{idx}b", "price": price, "size": 3000},
                    ],
                },
            )
        _write_manifest(date_dir / "manifest.json", entries)

        view = get_analytics_view(
            str(tmp_path),
            sport="mlb",
            price_quality_filter="all",
            pregame_min_cum_vol=5000,
        )
        game_row = view[view["match_id"] == "mlb-2"].iloc[0]
        summary = build_analysis_summary(game_row, view)

        assert summary["population_games"] == 3
        assert summary["open"]["team"] == "Home2"
        assert summary["open"]["interpretable_band"] == "Lower Moderate"
        assert summary["open"]["quantile_band"] == "Q2"
        assert summary["open"]["quantile_cutoffs"] is not None

    def test_available_sports_reflect_collected_records(self, tmp_path):
        date_dir = tmp_path / "2026-04-10"
        _write_manifest(
            date_dir / "manifest.json",
            [
                {
                    "match_id": "nba-1",
                    "sport": "nba",
                    "status": "collected",
                    "away_team": "A",
                    "home_team": "B",
                    "outcomes": ["A", "B"],
                    "token_ids": ["t1", "t2"],
                },
                {
                    "match_id": "mlb-1",
                    "sport": "mlb",
                    "status": "collected",
                    "away_team": "C",
                    "home_team": "D",
                    "outcomes": ["C", "D"],
                    "token_ids": ["u1", "u2"],
                },
            ],
        )
        for match_id, sport, token_a, token_b in [
            ("nba-1", "nba", "t1", "t2"),
            ("mlb-1", "mlb", "u1", "u2"),
        ]:
            _write_trade_file(
                date_dir / f"{match_id}_trades.json.gz",
                {
                    "match_id": match_id,
                    "sport": sport,
                    "price_checkpoints_meta": {"price_quality": "exact"},
                    "price_checkpoints": {
                        token_a: {
                            "selected_early_price": 0.4,
                            "selected_early_price_source": "clob_open",
                            "last_pregame_trade_price": 0.4,
                        },
                        token_b: {
                            "selected_early_price": 0.6,
                            "selected_early_price_source": "clob_open",
                            "last_pregame_trade_price": 0.6,
                        },
                    },
                    "trades": [
                        {"timestamp": 1, "asset": token_a, "price": 0.4, "size": 3000},
                        {"timestamp": 2, "asset": token_b, "price": 0.6, "size": 3000},
                    ],
                },
            )

        sports = get_available_sports(str(tmp_path), pregame_min_cum_vol=5000)
        assert sports == ["mlb", "nba"]

    def test_open_regime_uses_first_trade_after_min_cum_vol(self, tmp_path):
        date_dir = tmp_path / "2026-04-10"
        _write_manifest(
            date_dir / "manifest.json",
            [{
                "match_id": "nba-threshold",
                "sport": "nba",
                "status": "collected",
                "away_team": "Away",
                "home_team": "Home",
                "outcomes": ["Away", "Home"],
                "token_ids": ["a1", "h1"],
                "gamma_start_time": "2026-04-10T19:00:00Z",
            }],
        )
        _write_trade_file(
            date_dir / "nba-threshold_trades.json.gz",
            {
                "match_id": "nba-threshold",
                "sport": "nba",
                "price_checkpoints_meta": {"price_quality": "inferred"},
                "price_checkpoints": {
                    "a1": {
                        "selected_early_price": 0.20,
                        "selected_early_price_source": "first_pregame_trade",
                        "last_pregame_trade_price": 0.45,
                    },
                    "h1": {
                        "selected_early_price": 0.80,
                        "selected_early_price_source": "first_pregame_trade",
                        "last_pregame_trade_price": 0.55,
                    },
                },
                "trades": [
                    {"timestamp": 1, "asset": "a1", "price": 0.20, "size": 1000},
                    {"timestamp": 2, "asset": "h1", "price": 0.80, "size": 1000},
                    {"timestamp": 3, "asset": "a1", "price": 0.45, "size": 4000},
                    {"timestamp": 4, "asset": "h1", "price": 0.55, "size": 1000},
                ],
            },
        )

        df = load_game_analytics(str(tmp_path), pregame_min_cum_vol=5000)
        row = df.iloc[0]
        assert row["open_favorite_team"] == "Home"
        assert row["open_favorite_price"] == 0.55
        assert row["open_price_source"] == "post_min_cum_vol_vwap_5m"

    def test_open_regime_marks_tie_when_prices_match(self, tmp_path):
        date_dir = tmp_path / "2026-04-10"
        _write_manifest(
            date_dir / "manifest.json",
            [{
                "match_id": "nba-tie",
                "sport": "nba",
                "status": "collected",
                "away_team": "Away",
                "home_team": "Home",
                "outcomes": ["Away", "Home"],
                "token_ids": ["a1", "h1"],
                "gamma_start_time": "2026-04-10T19:00:00Z",
            }],
        )
        _write_trade_file(
            date_dir / "nba-tie_trades.json.gz",
            {
                "match_id": "nba-tie",
                "sport": "nba",
                "price_checkpoints_meta": {"price_quality": "exact"},
                "price_checkpoints": {
                    "a1": {
                        "selected_early_price": 0.5,
                        "selected_early_price_source": "clob_open",
                        "last_pregame_trade_price": 0.50,
                    },
                    "h1": {
                        "selected_early_price": 0.5,
                        "selected_early_price_source": "clob_open",
                        "last_pregame_trade_price": 0.50,
                    },
                },
                "trades": [
                    {"timestamp": 1, "asset": "a1", "price": 0.5, "size": 3000},
                    {"timestamp": 2, "asset": "h1", "price": 0.5, "size": 3000},
                ],
            },
        )

        df = load_game_analytics(str(tmp_path), pregame_min_cum_vol=0)
        row = df.iloc[0]
        assert row["open_favorite_team"] == "Tie"
        assert row["open_favorite_price"] == 0.5

    def test_open_regime_uses_post_threshold_vwap_window(self, tmp_path):
        date_dir = tmp_path / "2026-04-10"
        _write_manifest(
            date_dir / "manifest.json",
            [{
                "match_id": "nba-vwap",
                "sport": "nba",
                "status": "collected",
                "away_team": "Away",
                "home_team": "Home",
                "outcomes": ["Away", "Home"],
                "token_ids": ["a1", "h1"],
                "gamma_start_time": "2026-04-10T19:00:00Z",
            }],
        )
        _write_trade_file(
            date_dir / "nba-vwap_trades.json.gz",
            {
                "match_id": "nba-vwap",
                "sport": "nba",
                "price_checkpoints_meta": {"price_quality": "exact"},
                "price_checkpoints": {
                    "a1": {
                        "selected_early_price": 0.46,
                        "selected_early_price_source": "clob_open",
                        "last_pregame_trade_price": 0.43,
                    },
                    "h1": {
                        "selected_early_price": 0.54,
                        "selected_early_price_source": "clob_open",
                        "last_pregame_trade_price": 0.57,
                    },
                },
                "trades": [
                    {"timestamp": 1, "asset": "a1", "price": 0.46, "size": 1000},
                    {"timestamp": 2, "asset": "h1", "price": 0.54, "size": 1000},
                    {"timestamp": 3, "asset": "a1", "price": 0.44, "size": 4000},
                    {"timestamp": 4, "asset": "h1", "price": 0.56, "size": 1000},
                    {"timestamp": 5, "asset": "a1", "price": 0.42, "size": 1000},
                    {"timestamp": 6, "asset": "h1", "price": 0.58, "size": 2000},
                ],
            },
        )

        df = load_game_analytics(str(tmp_path), pregame_min_cum_vol=5000)
        row = df.iloc[0]
        assert row["open_favorite_team"] == "Home"
        assert row["open_favorite_price"] == pytest.approx((0.56 * 1000 + 0.58 * 2000) / 3000)
        assert row["open_price_source"] == "post_min_cum_vol_vwap_5m"
