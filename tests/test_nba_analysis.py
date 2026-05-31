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


def _ingame_metrics_fixture():
    """Two-team in-game scenario where open and tip-off favorites differ.

    Away-side in-game prices: 0.20, 0.50, 0.40 -> min 0.20, max 0.50.
    Home-side (1 - away):      0.80, 0.50, 0.60 -> min 0.50, max 0.80.
    """
    tipoff = pd.Timestamp("2026-04-10T19:00:00Z")
    trades_df = pd.DataFrame(
        {
            "datetime": [
                tipoff + pd.Timedelta(minutes=1),
                tipoff + pd.Timedelta(minutes=5),
                tipoff + pd.Timedelta(minutes=10),
            ],
            "asset": ["a1", "a1", "a1"],
            "price": [0.20, 0.50, 0.40],
            "size": [1000, 1000, 1000],
        }
    )
    events = [
        {"time_actual_dt": tipoff, "away_score": 0, "home_score": 0},
        {
            "time_actual_dt": tipoff + pd.Timedelta(minutes=15),
            "away_score": 100,
            "home_score": 98,
        },
    ]
    manifest = {"token_ids": ["a1", "h1"], "outcomes": ["Away", "Home"]}
    return trades_df, events, manifest


def test_in_game_metrics_track_open_and_tipoff_sides_independently():
    from nba_analysis import _compute_in_game_open_favorite_metrics

    trades_df, events, manifest = _ingame_metrics_fixture()
    metrics = _compute_in_game_open_favorite_metrics(
        trades_df,
        events,
        manifest,
        ChartSettings(post_game_buffer_min=10),
        open_favorite_team="Away",
        open_favorite_price=0.45,
        tipoff_favorite_team="Home",
        tipoff_favorite_price=0.55,
    )

    # Open favorite = Away side
    assert metrics["open_favorite_in_game_min_price"] == pytest.approx(0.20)
    assert metrics["open_favorite_in_game_max_price"] == pytest.approx(0.50)
    assert metrics["open_favorite_max_adverse_excursion"] == pytest.approx(0.25)
    assert metrics["open_favorite_max_favorable_excursion"] == pytest.approx(0.05)

    # Tip-off favorite = Home side (distinct path)
    assert metrics["tipoff_favorite_in_game_min_price"] == pytest.approx(0.50)
    assert metrics["tipoff_favorite_in_game_max_price"] == pytest.approx(0.80)
    assert metrics["tipoff_favorite_max_adverse_excursion"] == pytest.approx(0.05)
    assert metrics["tipoff_favorite_max_favorable_excursion"] == pytest.approx(0.25)
    assert metrics["tipoff_favorite_max_adverse_excursion_pct"] == pytest.approx(0.05 / 0.55)

    # The two sides genuinely differ
    assert (
        metrics["tipoff_favorite_in_game_min_price"]
        != metrics["open_favorite_in_game_min_price"]
    )


def test_in_game_metrics_parity_when_open_equals_tipoff_favorite():
    from nba_analysis import _compute_in_game_open_favorite_metrics

    trades_df, events, manifest = _ingame_metrics_fixture()
    metrics = _compute_in_game_open_favorite_metrics(
        trades_df,
        events,
        manifest,
        ChartSettings(post_game_buffer_min=10),
        open_favorite_team="Away",
        open_favorite_price=0.45,
        tipoff_favorite_team="Away",
        tipoff_favorite_price=0.45,
    )
    assert (
        metrics["tipoff_favorite_in_game_min_price"]
        == metrics["open_favorite_in_game_min_price"]
    )
    assert (
        metrics["tipoff_favorite_in_game_max_price"]
        == metrics["open_favorite_in_game_max_price"]
    )
    assert (
        metrics["tipoff_favorite_max_adverse_excursion"]
        == metrics["open_favorite_max_adverse_excursion"]
    )


def test_in_game_metrics_tipoff_none_when_team_undetermined():
    from nba_analysis import _compute_in_game_open_favorite_metrics

    trades_df, events, manifest = _ingame_metrics_fixture()
    metrics = _compute_in_game_open_favorite_metrics(
        trades_df,
        events,
        manifest,
        ChartSettings(post_game_buffer_min=10),
        open_favorite_team="Away",
        open_favorite_price=0.45,
        tipoff_favorite_team=None,
        tipoff_favorite_price=None,
    )
    assert metrics["tipoff_favorite_in_game_min_price"] is None
    assert metrics["tipoff_favorite_max_adverse_excursion"] is None


def _entry_window_fixture():
    tipoff = pd.Timestamp("2026-04-10T19:00:00Z")
    trades_df = pd.DataFrame(
        {
            "datetime": [
                tipoff - pd.Timedelta(minutes=30),
                tipoff - pd.Timedelta(minutes=20),
                tipoff - pd.Timedelta(minutes=10),
                tipoff + pd.Timedelta(minutes=5),  # post-tip, must be excluded
            ],
            "asset": ["a1", "h1", "a1", "a1"],
            "price": [0.30, 0.40, 0.50, 0.99],
            "size": [100, 200, 300, 999],
        }
    )
    manifest = {"token_ids": ["a1", "h1"], "outcomes": ["Away", "Home"]}
    return trades_df, manifest, tipoff


def test_entry_window_size_weighted_last_n_by_side():
    from nba_analysis import _compute_tipoff_entry_window_price

    trades_df, manifest, tipoff = _entry_window_fixture()

    # Away favorite, last 2 pre-tip away-prices = 0.60, 0.50 (sizes 200, 300)
    price, n_used = _compute_tipoff_entry_window_price(
        trades_df, manifest, "Away", tipoff, n_trades=2
    )
    assert n_used == 2
    assert price == pytest.approx((0.60 * 200 + 0.50 * 300) / 500)  # 0.54

    # Home favorite is the complement
    price_home, _ = _compute_tipoff_entry_window_price(
        trades_df, manifest, "Home", tipoff, n_trades=2
    )
    assert price_home == pytest.approx(0.46)


def test_entry_window_truncates_when_fewer_than_n():
    from nba_analysis import _compute_tipoff_entry_window_price

    trades_df, manifest, tipoff = _entry_window_fixture()
    price, n_used = _compute_tipoff_entry_window_price(
        trades_df, manifest, "Away", tipoff, n_trades=10
    )
    assert n_used == 3  # only 3 pre-tip trades exist
    assert price == pytest.approx((0.30 * 100 + 0.60 * 200 + 0.50 * 300) / 600)  # 0.50


def test_entry_window_none_when_undetermined_or_zero_n():
    from nba_analysis import _compute_tipoff_entry_window_price

    trades_df, manifest, tipoff = _entry_window_fixture()
    assert _compute_tipoff_entry_window_price(trades_df, manifest, None, tipoff, 30) == (None, 0)
    assert _compute_tipoff_entry_window_price(trades_df, manifest, "Away", tipoff, 0) == (None, 0)
    assert _compute_tipoff_entry_window_price(trades_df, manifest, "Away", None, 30) == (None, 0)


def test_band_outcome_distribution_percentiles_and_shape():
    service = NBAOpenTipoffAnalysisService("/tmp", ChartSettings())
    dataset = pd.DataFrame(
        {
            "tipoff_interpretable_band": (
                ["Upper Strong"] * 6 + ["Lower Strong"] * 6
            ),
            "tipoff_favorite_won": (
                [True, True, True, False, False, False]
                + [True, True, True, False, False, False]
            ),
            "tipoff_favorite_in_game_min_price": [
                0.78, 0.80, 0.82, 0.40, 0.50, 0.60,   # Upper Strong
                0.60, 0.63, 0.66, 0.20, 0.30, 0.40,   # Lower Strong
            ],
        }
    )
    dist = service.build_band_outcome_distribution(dataset)

    assert list(dist.columns) == [
        "band", "outcome", "n_games", "p05", "p10", "p25", "p50", "p75", "p90", "p95",
    ]
    assert len(dist) == 4  # 2 bands x 2 outcomes
    # Upper Strong ordered before Lower Strong per GROUP_ORDERINGS? Lower Strong
    # precedes Upper Strong in INTERPRETABLE_BAND_LABELS, so it sorts first.
    assert dist["band"].tolist() == [
        "Lower Strong", "Lower Strong", "Upper Strong", "Upper Strong",
    ]
    by_cell = {(r["band"], r["outcome"]): r for _, r in dist.iterrows()}
    assert by_cell[("Upper Strong", "win")]["n_games"] == 3
    assert by_cell[("Upper Strong", "win")]["p50"] == pytest.approx(0.80)
    assert by_cell[("Upper Strong", "loss")]["p50"] == pytest.approx(0.50)
    assert by_cell[("Lower Strong", "win")]["p50"] == pytest.approx(0.63)
    assert by_cell[("Lower Strong", "loss")]["p50"] == pytest.approx(0.30)


def test_band_outcome_distribution_skips_null_outcome_and_empty():
    service = NBAOpenTipoffAnalysisService("/tmp", ChartSettings())
    assert service.build_band_outcome_distribution(pd.DataFrame()).empty

    dataset = pd.DataFrame(
        {
            "tipoff_interpretable_band": ["Upper Strong", "Upper Strong"],
            "tipoff_favorite_won": [True, None],  # one null outcome -> excluded
            "tipoff_favorite_in_game_min_price": [0.80, 0.10],
        }
    )
    dist = service.build_band_outcome_distribution(dataset)
    assert len(dist) == 1
    assert dist.iloc[0]["outcome"] == "win"
    assert dist.iloc[0]["n_games"] == 1


def _ev_grid_dataset(bands, wons, entries, mins):
    return pd.DataFrame(
        {
            "tipoff_interpretable_band": bands,
            "tipoff_favorite_won": wons,
            "tipoff_favorite_avg_last_n_pretip_price": entries,
            "tipoff_favorite_in_game_min_price": mins,
        }
    )


def test_ev_grid_all_winners_argmax_is_zero_stop():
    service = NBAOpenTipoffAnalysisService("/tmp", ChartSettings())
    dataset = _ev_grid_dataset(
        bands=["Upper Strong"] * 3,
        wons=[True, True, True],
        entries=[0.55, 0.55, 0.55],
        mins=[0.50, 0.60, 0.70],
    )
    grid = service.build_band_stop_loss_ev_grid(dataset, ChartSettings())
    assert list(grid.columns) == list(service._EV_GRID_COLUMNS)
    argmax = grid[grid["is_argmax"]]
    assert len(argmax) == 1
    assert argmax.iloc[0]["stop_price"] == pytest.approx(0.0)
    # No-stop reference for a 100%-win band = 1 - E
    assert grid.iloc[0]["ev_no_stop_reference"] == pytest.approx(1.0 - 0.55)


def test_ev_grid_frictionless_no_stop_reference_closed_form():
    service = NBAOpenTipoffAnalysisService("/tmp", ChartSettings())
    # 2 winners, 2 losers -> win_rate 0.5, E = 0.50
    dataset = _ev_grid_dataset(
        bands=["Lower Strong"] * 4,
        wons=[True, True, False, False],
        entries=[0.50, 0.50, 0.50, 0.50],
        mins=[0.55, 0.60, 0.30, 0.35],
    )
    grid = service.build_band_stop_loss_ev_grid(dataset, ChartSettings())
    expected = 0.5 * (1.0 - 0.50) + 0.5 * (-0.50)  # = 0.0
    assert grid["ev_no_stop_reference"].iloc[0] == pytest.approx(expected)


def test_ev_grid_stop_helps_all_loser_band():
    service = NBAOpenTipoffAnalysisService("/tmp", ChartSettings())
    dataset = _ev_grid_dataset(
        bands=["Lower Strong"] * 3,
        wons=[False, False, False],
        entries=[0.50, 0.50, 0.50],
        mins=[0.30, 0.30, 0.30],
    )
    grid = service.build_band_stop_loss_ev_grid(dataset, ChartSettings())
    assert grid["ev_no_stop_reference"].iloc[0] == pytest.approx(-0.50)
    argmax_ev = grid.loc[grid["is_argmax"], "ev_per_unit_stake"].iloc[0]
    # A stop above 0.30 caps the loss, so the best EV beats no-stop (-0.50).
    assert argmax_ev > -0.50


def test_ev_grid_one_argmax_per_band_and_empty_edge():
    service = NBAOpenTipoffAnalysisService("/tmp", ChartSettings())
    dataset = _ev_grid_dataset(
        bands=["Upper Strong"] * 2 + ["Lower Strong"] * 2,
        wons=[True, False, True, False],
        entries=[0.60, 0.60, 0.45, 0.45],
        mins=[0.70, 0.20, 0.50, 0.15],
    )
    grid = service.build_band_stop_loss_ev_grid(dataset, ChartSettings())
    per_band = grid.groupby("band")["is_argmax"].sum()
    assert (per_band == 1).all()

    # Band with no outcome data -> no rows for it.
    no_outcome = _ev_grid_dataset(
        bands=["Upper Strong"],
        wons=[None],
        entries=[0.60],
        mins=[0.70],
    )
    assert service.build_band_stop_loss_ev_grid(no_outcome, ChartSettings()).empty


def test_ev_grid_fee_shifts_ev_down():
    service = NBAOpenTipoffAnalysisService("/tmp", ChartSettings())
    dataset = _ev_grid_dataset(
        bands=["Lower Strong"] * 4,
        wons=[True, True, False, False],
        entries=[0.50, 0.50, 0.50, 0.50],
        mins=[0.55, 0.60, 0.30, 0.35],
    )
    base = service.build_band_stop_loss_ev_grid(dataset, ChartSettings())
    fee = service.build_band_stop_loss_ev_grid(
        dataset, ChartSettings(stop_loss_fee_bps=100.0)  # 1% = 0.01
    )
    assert fee["ev_no_stop_reference"].iloc[0] == pytest.approx(
        base["ev_no_stop_reference"].iloc[0] - 0.01
    )


def test_ev_grid_excludes_stops_at_or_above_entry():
    service = NBAOpenTipoffAnalysisService("/tmp", ChartSettings())
    dataset = _ev_grid_dataset(
        bands=["Lower Strong"] * 4,
        wons=[True, True, False, False],
        entries=[0.50, 0.50, 0.50, 0.50],
        mins=[0.55, 0.60, 0.30, 0.35],
    )
    grid = service.build_band_stop_loss_ev_grid(dataset, ChartSettings())
    E = grid["entry_price_used"].iloc[0]
    # No stop at or above entry survives, and argmax is no longer pinned to ~0.98.
    assert (grid["stop_price"] < E).all()
    assert grid.loc[grid["is_argmax"], "stop_price"].iloc[0] < E


def test_ev_grid_slippage_worsens_stopped_fill():
    service = NBAOpenTipoffAnalysisService("/tmp", ChartSettings())
    # All losers whose min price dips to 0.30: every positive stop is touched,
    # so slippage degrades the fill at the active stop rows.
    dataset = _ev_grid_dataset(
        bands=["Lower Strong"] * 3,
        wons=[False, False, False],
        entries=[0.50, 0.50, 0.50],
        mins=[0.30, 0.30, 0.30],
    )
    base = service.build_band_stop_loss_ev_grid(dataset, ChartSettings())
    slip = service.build_band_stop_loss_ev_grid(
        dataset, ChartSettings(stop_loss_slippage_bps=200.0)  # 2% = 0.02
    )

    # Pick a stop above the loser min (0.30) but below entry (0.50) so the stop
    # is triggered for every game; the only EV difference is slippage on the fill.
    base_row = base[base["stop_price"].round(4) == 0.40].iloc[0]
    slip_row = slip[slip["stop_price"].round(4) == 0.40].iloc[0]
    assert slip_row["loss_stopout_rate"] == pytest.approx(1.0)
    # loss_rate=1, stopout_rate=1 -> EV = (stop - slippage) - E; slippage 0.02.
    assert slip_row["ev_per_unit_stake"] == pytest.approx(
        base_row["ev_per_unit_stake"] - 0.02
    )


def test_ev_grid_no_stop_reference_row_ignores_slippage():
    service = NBAOpenTipoffAnalysisService("/tmp", ChartSettings())
    dataset = _ev_grid_dataset(
        bands=["Lower Strong"] * 3,
        wons=[False, False, False],
        entries=[0.50, 0.50, 0.50],
        mins=[0.30, 0.30, 0.30],
    )
    grid = service.build_band_stop_loss_ev_grid(
        dataset, ChartSettings(stop_loss_slippage_bps=200.0)
    )
    zero_stop = grid[grid["stop_price"].round(4) == 0.0].iloc[0]
    # stop==0 is the never-triggered reference: equals ev_no_stop, unaffected
    # by slippage, with both stopout rates pinned to 0.
    assert zero_stop["ev_per_unit_stake"] == pytest.approx(
        zero_stop["ev_no_stop_reference"]
    )
    assert zero_stop["win_stopout_rate"] == pytest.approx(0.0)
    assert zero_stop["loss_stopout_rate"] == pytest.approx(0.0)


def test_resolve_score_tipoff_time_picks_earliest_score_event():
    from nba_analysis import _resolve_score_tipoff_time

    t0 = pd.Timestamp("2026-04-10T19:00:00Z")
    events = [
        {"time_actual_dt": t0 + pd.Timedelta(minutes=20), "away_score": 30, "home_score": 28},
        {"time_actual_dt": t0, "away_score": 0, "home_score": 0},
        # No score fields -> not a score event, ignored even though earlier.
        {"time_actual_dt": t0 - pd.Timedelta(minutes=5)},
    ]
    assert _resolve_score_tipoff_time(events) == t0


def test_resolve_score_tipoff_time_none_when_no_score_events():
    from nba_analysis import _resolve_score_tipoff_time

    assert _resolve_score_tipoff_time(None) is None
    assert _resolve_score_tipoff_time([]) is None
    # Timestamped but missing score fields -> no usable tip-off.
    assert _resolve_score_tipoff_time(
        [{"time_actual_dt": pd.Timestamp("2026-04-10T19:00:00Z")}]
    ) is None


def test_entry_window_none_when_no_pretip_trades():
    from nba_analysis import _compute_tipoff_entry_window_price

    _, manifest, tipoff = _entry_window_fixture()
    # All trades at/after tip-off -> empty pre-tip window.
    post_only = pd.DataFrame(
        {
            "datetime": [tipoff, tipoff + pd.Timedelta(minutes=1)],
            "asset": ["a1", "h1"],
            "price": [0.50, 0.50],
            "size": [100, 100],
        }
    )
    assert _compute_tipoff_entry_window_price(
        post_only, manifest, "Away", tipoff, n_trades=5
    ) == (None, 0)


def test_entry_window_none_when_zero_total_size():
    from nba_analysis import _compute_tipoff_entry_window_price

    tipoff = pd.Timestamp("2026-04-10T19:00:00Z")
    zero_size = pd.DataFrame(
        {
            "datetime": [tipoff - pd.Timedelta(minutes=10), tipoff - pd.Timedelta(minutes=5)],
            "asset": ["a1", "a1"],
            "price": [0.40, 0.50],
            "size": [0, 0],
        }
    )
    manifest = {"token_ids": ["a1", "h1"], "outcomes": ["Away", "Home"]}
    price, n_used = _compute_tipoff_entry_window_price(
        zero_size, manifest, "Away", tipoff, n_trades=5
    )
    # Window is non-empty (n_used reflects consumed rows) but unweightable.
    assert price is None
    assert n_used == 2


def test_compute_detail_row_threads_tipoff_entry_window_keys():
    from nba_analysis import _compute_nba_detail_row_from_game

    trades_df, events, manifest = _ingame_metrics_fixture()
    game = {"trades_df": trades_df, "events": events, "manifest": manifest}
    details = _compute_nba_detail_row_from_game(
        game,
        ChartSettings(tipoff_entry_window_trades=5, post_game_buffer_min=10),
        open_favorite_team="Away",
        open_favorite_price=0.45,
        tipoff_favorite_team="Home",
        tipoff_favorite_price=0.55,
    )
    # Tip-off in-game path keys present from the threaded tip-off favorite.
    assert details["tipoff_favorite_in_game_min_price"] is not None
    # Entry-window keys wired through from the new helper.
    assert "tipoff_favorite_avg_last_n_pretip_price" in details
    assert "tipoff_entry_window_n_used" in details
    assert details["tipoff_entry_window_n_used"] >= 0
