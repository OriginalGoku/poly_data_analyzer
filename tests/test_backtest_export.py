"""Tests for backtest results export (per-position schema)."""
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from backtest.backtest_export import export_backtest_results


@pytest.fixture
def mock_results():
    per_position = pd.DataFrame(
        [
            {
                "scenario_name": "dip_buy_favorite",
                "sweep_axis_trigger.threshold_cents": 5,
                "date": "2026-03-23",
                "match_id": "nba_game_1",
                "sport": "nba",
                "side": "favorite",
                "entry_team": "LAL",
                "entry_token_id": "tok_1",
                "entry_time": "2026-03-23T19:30:00",
                "entry_price": 0.81,
                "exit_time": "2026-03-23T20:30:00",
                "exit_price": 0.87,
                "exit_kind": "settlement",
                "status": "filled",
                "position_index_in_game": 0,
                "settlement_payout": 1.0,
                "pnl": 6.0,
                "roi_pct": 0.07,
                "hold_seconds": 3600,
                "max_drawdown_cents": 1.5,
                "baseline_buy_at_open_roi": 0.05,
                "baseline_buy_at_tipoff_roi": 0.04,
                "baseline_buy_first_ingame_roi": 0.06,
            },
            {
                "scenario_name": "dip_buy_favorite",
                "sweep_axis_trigger.threshold_cents": 10,
                "date": "2026-03-24",
                "match_id": "nba_game_2",
                "sport": "nba",
                "side": "favorite",
                "entry_team": "BOS",
                "entry_token_id": "tok_2",
                "entry_time": "2026-03-24T19:30:00",
                "entry_price": 0.75,
                "exit_time": "2026-03-24T20:00:00",
                "exit_price": 0.80,
                "exit_kind": "tp_sl",
                "status": "filled",
                "position_index_in_game": 0,
                "settlement_payout": None,
                "pnl": 4.5,
                "roi_pct": 0.06,
                "hold_seconds": 1800,
                "max_drawdown_cents": 0.5,
                "baseline_buy_at_open_roi": 0.03,
                "baseline_buy_at_tipoff_roi": 0.02,
                "baseline_buy_first_ingame_roi": 0.04,
            },
        ]
    )

    aggregation = pd.DataFrame(
        [
            {
                "scenario_name": "dip_buy_favorite",
                "sweep_axis_trigger.threshold_cents": 5,
                "count": 1,
                "mean_roi_pct": 0.07,
                "win_rate": 1.0,
                "mean_hold_seconds": 3600.0,
                "mean_drawdown_cents": 1.5,
                "forced_close_count": 0,
            },
            {
                "scenario_name": "dip_buy_favorite",
                "sweep_axis_trigger.threshold_cents": 10,
                "count": 1,
                "mean_roi_pct": 0.06,
                "win_rate": 1.0,
                "mean_hold_seconds": 1800.0,
                "mean_drawdown_cents": 0.5,
                "forced_close_count": 0,
            },
        ]
    )

    return per_position, aggregation


def test_export_writes_all_files(mock_results):
    per_position, aggregation = mock_results
    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(
            per_position_df=per_position,
            aggregation_df=aggregation,
            output_path=tmpdir,
            heatmap_dims=("scenario_name", "sweep_axis_trigger.threshold_cents"),
        )
        assert Path(f"{tmpdir}/results_positions.csv").exists()
        assert Path(f"{tmpdir}/results_positions.json").exists()
        assert Path(f"{tmpdir}/results_aggregation.csv").exists()
        assert Path(f"{tmpdir}/results_aggregation.json").exists()
        assert Path(f"{tmpdir}/roi_heatmap.html").exists()


def test_per_position_csv_round_trip_preserves_columns(mock_results):
    per_position, aggregation = mock_results
    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(per_position, aggregation, tmpdir)
        loaded = pd.read_csv(f"{tmpdir}/results_positions.csv")
        assert len(loaded) == len(per_position)
        assert "scenario_name" in loaded.columns
        assert "sweep_axis_trigger.threshold_cents" in loaded.columns
        assert "position_index_in_game" in loaded.columns
        assert set(per_position.columns) == set(loaded.columns)


def test_aggregation_csv_round_trip(mock_results):
    per_position, aggregation = mock_results
    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(per_position, aggregation, tmpdir)
        loaded = pd.read_csv(f"{tmpdir}/results_aggregation.csv")
        assert len(loaded) == len(aggregation)
        assert "scenario_name" in loaded.columns
        assert "mean_roi_pct" in loaded.columns


def test_json_round_trip(mock_results):
    per_position, aggregation = mock_results
    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(per_position, aggregation, tmpdir)
        pos_loaded = pd.read_json(f"{tmpdir}/results_positions.json")
        agg_loaded = pd.read_json(f"{tmpdir}/results_aggregation.json")
        assert len(pos_loaded) == len(per_position)
        assert len(agg_loaded) == len(aggregation)


def test_heatmap_2d_renders(mock_results):
    per_position, aggregation = mock_results
    extra = aggregation.copy()
    extra["scenario_name"] = "another_scenario"
    extra["mean_roi_pct"] = [0.02, 0.03]
    agg_2d = pd.concat([aggregation, extra], ignore_index=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(
            per_position,
            agg_2d,
            tmpdir,
            heatmap_dims=("scenario_name", "sweep_axis_trigger.threshold_cents"),
        )
        assert Path(f"{tmpdir}/roi_heatmap.html").exists()


def test_heatmap_missing_axis_falls_back_to_1xN(mock_results):
    per_position, aggregation = mock_results
    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(
            per_position,
            aggregation,
            tmpdir,
            heatmap_dims=("scenario_name", "nonexistent_axis"),
        )
        assert Path(f"{tmpdir}/roi_heatmap.html").exists()


def test_heatmap_skipped_when_dims_none(mock_results):
    per_position, aggregation = mock_results
    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(per_position, aggregation, tmpdir, heatmap_dims=None)
        assert not Path(f"{tmpdir}/roi_heatmap.html").exists()
