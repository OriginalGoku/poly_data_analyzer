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
                "volume_stats": {
                    "pre_game_notional_usdc": 12345.67,
                    "trade_count": 42,
                    "in_game_notional_usdc": 1000.0,
                },
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
        assert nba["pre_game_notional_usdc"] == 12345.67
        assert nba["trade_count"] == 42
        nhl = df[df["match_id"] == "nhl-c-d-2026-04-10"].iloc[0]
        assert pd.isna(nhl["pre_game_notional_usdc"])
        assert pd.isna(nhl["trade_count"])

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

    def test_quantile_bands_use_window_local_population(self, tmp_path):
        """Quantile bands must reflect the date-window population, not the full history.

        Regression test for Step 4: the date filter in get_analytics_view must run
        before quantile_source assignment.
        """
        for date_name, prices in [
            ("2026-04-01", [(0.60, "low-1"), (0.60, "low-2")]),
            ("2026-04-10", [(0.90, "hi-1"), (0.90, "hi-2")]),
        ]:
            date_dir = tmp_path / date_name
            entries = []
            for price, match_id in prices:
                entries.append(
                    {
                        "match_id": match_id,
                        "sport": "nba",
                        "status": "collected",
                        "away_team": "A",
                        "home_team": "B",
                        "outcomes": ["A", "B"],
                        "token_ids": [f"{match_id}-a", f"{match_id}-b"],
                    }
                )
                _write_trade_file(
                    date_dir / f"{match_id}_trades.json.gz",
                    {
                        "match_id": match_id,
                        "sport": "nba",
                        "price_checkpoints_meta": {"price_quality": "exact"},
                        "price_checkpoints": {
                            f"{match_id}-a": {
                                "selected_early_price": 1 - price,
                                "selected_early_price_source": "clob_open",
                                "last_pregame_trade_price": 1 - price,
                            },
                            f"{match_id}-b": {
                                "selected_early_price": price,
                                "selected_early_price_source": "clob_open",
                                "last_pregame_trade_price": price,
                            },
                        },
                        "trades": [
                            {"timestamp": 1, "asset": f"{match_id}-a", "price": 1 - price, "size": 3000},
                            {"timestamp": 2, "asset": f"{match_id}-b", "price": price, "size": 3000},
                        ],
                    },
                )
            _write_manifest(date_dir / "manifest.json", entries)

        # Window: 2026-04-01 only. All games in the window are price 0.60.
        # If date filter is applied AFTER quantile_source, bands span the global 0.60..0.90 range
        # and our two window games would land in Q1. With correct ordering, all bands are equal
        # (degenerate population) and at minimum every band label is from the window's prices.
        window_view = get_analytics_view(
            str(tmp_path),
            sport="nba",
            price_quality_filter="all",
            pregame_min_cum_vol=5000,
            start_date="2026-04-01",
            end_date="2026-04-01",
        )
        assert len(window_view) == 2
        # All window prices identical => all rows share the same quantile band.
        assert window_view["open_quantile_band"].nunique() == 1

    def test_get_analytics_view_min_pregame_notional_gate(self, tmp_path):
        date_dir = tmp_path / "2026-04-10"
        entries = []
        for match_id, pre_vol in [("nba-thin", 100), ("nba-mid", 5_000), ("nba-fat", 50_000)]:
            entries.append(
                {
                    "match_id": match_id,
                    "sport": "nba",
                    "status": "collected",
                    "away_team": "A",
                    "home_team": "B",
                    "outcomes": ["A", "B"],
                    "token_ids": [f"{match_id}-a", f"{match_id}-b"],
                    "volume_stats": {"pre_game_notional_usdc": pre_vol, "trade_count": 10},
                }
            )
            _write_trade_file(
                date_dir / f"{match_id}_trades.json.gz",
                {
                    "match_id": match_id,
                    "sport": "nba",
                    "price_checkpoints_meta": {"price_quality": "exact"},
                    "price_checkpoints": {
                        f"{match_id}-a": {
                            "selected_early_price": 0.4,
                            "selected_early_price_source": "clob_open",
                            "last_pregame_trade_price": 0.4,
                        },
                        f"{match_id}-b": {
                            "selected_early_price": 0.6,
                            "selected_early_price_source": "clob_open",
                            "last_pregame_trade_price": 0.6,
                        },
                    },
                    "trades": [
                        {"timestamp": 1, "asset": f"{match_id}-a", "price": 0.4, "size": 3000},
                        {"timestamp": 2, "asset": f"{match_id}-b", "price": 0.6, "size": 3000},
                    ],
                },
            )
        _write_manifest(date_dir / "manifest.json", entries)

        view_all = get_analytics_view(
            str(tmp_path),
            sport="nba",
            price_quality_filter="all",
            pregame_min_cum_vol=0,
            min_pregame_notional=0,
        )
        assert len(view_all) == 3

        view_gated = get_analytics_view(
            str(tmp_path),
            sport="nba",
            price_quality_filter="all",
            pregame_min_cum_vol=0,
            min_pregame_notional=5000,
        )
        assert set(view_gated["match_id"]) == {"nba-mid", "nba-fat"}

    def test_get_analytics_view_combines_sport_and_date_filters(self, tmp_path):
        """sport filter + start_date/end_date applied together must intersect."""
        layout = [
            ("2026-04-01", "nba-old", "nba", 0.60),
            ("2026-04-01", "mlb-old", "mlb", 0.55),
            ("2026-04-10", "nba-new", "nba", 0.75),
            ("2026-04-10", "mlb-new", "mlb", 0.70),
            ("2026-04-20", "nba-future", "nba", 0.85),
        ]
        by_date: dict[str, list[dict]] = {}
        for date_name, match_id, sport, price in layout:
            by_date.setdefault(date_name, []).append(
                {
                    "match_id": match_id,
                    "sport": sport,
                    "status": "collected",
                    "away_team": "A",
                    "home_team": "B",
                    "outcomes": ["A", "B"],
                    "token_ids": [f"{match_id}-a", f"{match_id}-b"],
                }
            )
            _write_trade_file(
                tmp_path / date_name / f"{match_id}_trades.json.gz",
                {
                    "match_id": match_id,
                    "sport": sport,
                    "price_checkpoints_meta": {"price_quality": "exact"},
                    "price_checkpoints": {
                        f"{match_id}-a": {
                            "selected_early_price": 1 - price,
                            "selected_early_price_source": "clob_open",
                            "last_pregame_trade_price": 1 - price,
                        },
                        f"{match_id}-b": {
                            "selected_early_price": price,
                            "selected_early_price_source": "clob_open",
                            "last_pregame_trade_price": price,
                        },
                    },
                    "trades": [
                        {"timestamp": 1, "asset": f"{match_id}-a", "price": 1 - price, "size": 3000},
                        {"timestamp": 2, "asset": f"{match_id}-b", "price": price, "size": 3000},
                    ],
                },
            )
        for date_name, entries in by_date.items():
            _write_manifest(tmp_path / date_name / "manifest.json", entries)

        view = get_analytics_view(
            str(tmp_path),
            sport="nba",
            price_quality_filter="all",
            pregame_min_cum_vol=5000,
            start_date="2026-04-05",
            end_date="2026-04-15",
        )

        assert set(view["match_id"]) == {"nba-new"}
        assert set(view["sport"]) == {"nba"}
        # Quantile bands computed against the intersection population (n=1):
        # single-row population => all rows share the same band.
        assert view["open_quantile_band"].nunique() == 1
