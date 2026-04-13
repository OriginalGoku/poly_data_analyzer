"""Tests for backtest results export."""
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from backtest_export import export_backtest_results


@pytest.fixture
def mock_results():
    """Create mock backtest results."""
    aggregated = pd.DataFrame(
        [
            {
                "dip_threshold": 10,
                "exit_type": "settlement",
                "fee_model": "taker",
                "total_games": 100,
                "games_with_entry": 30,
                "games_settled": 25,
                "total_trades": 30,
                "gross_roi_mean": 0.03,
                "net_roi_mean": 0.025,
                "win_rate": 0.6,
                "avg_entry_price": 0.80,
                "avg_hold_minutes": 15.0,
            },
        ]
    )

    per_game = pd.DataFrame(
        [
            {
                "match_id": "nba_game_1",
                "date": "2026-03-23",
                "sport": "nba",
                "entry_price": 0.81,
                "exit_price": 0.87,
                "roi_pct": 0.07,
                "settlement_occurred": True,
                "true_pnl_cents": 19.0,
            },
            {
                "match_id": "nba_game_2",
                "date": "2026-03-24",
                "sport": "nba",
                "entry_price": None,
                "exit_price": None,
                "roi_pct": 0,
                "settlement_occurred": False,
                "true_pnl_cents": None,
            },
        ]
    )

    return aggregated, per_game


def test_export_backtest_results(mock_results):
    """Test exporting results."""
    aggregated, per_game = mock_results

    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(
            aggregated_df=aggregated,
            per_game_df=per_game,
            output_dir=tmpdir,
        )

        # Check files exist
        assert Path(f"{tmpdir}/results_aggregated.csv").exists()
        assert Path(f"{tmpdir}/results_aggregated.json").exists()
        assert Path(f"{tmpdir}/results_per_game.csv").exists()
        assert Path(f"{tmpdir}/results_per_game.json").exists()
        assert Path(f"{tmpdir}/BACKTEST_SUMMARY.txt").exists()
        assert Path(f"{tmpdir}/SCHEMA.md").exists()
        assert Path(f"{tmpdir}/roi_heatmap.html").exists()


def test_export_csv_round_trip(mock_results):
    """Test that CSV export/import round-trip works."""
    aggregated, per_game = mock_results

    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(
            aggregated_df=aggregated,
            per_game_df=per_game,
            output_dir=tmpdir,
        )

        # Read back CSV
        agg_loaded = pd.read_csv(f"{tmpdir}/results_aggregated.csv")
        per_game_loaded = pd.read_csv(f"{tmpdir}/results_per_game.csv")

        assert len(agg_loaded) == len(aggregated)
        assert len(per_game_loaded) == len(per_game)


def test_export_json_round_trip(mock_results):
    """Test that JSON export/import round-trip works."""
    aggregated, per_game = mock_results

    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(
            aggregated_df=aggregated,
            per_game_df=per_game,
            output_dir=tmpdir,
        )

        # Read back JSON
        agg_loaded = pd.read_json(f"{tmpdir}/results_aggregated.json")
        per_game_loaded = pd.read_json(f"{tmpdir}/results_per_game.json")

        assert len(agg_loaded) == len(aggregated)
        assert len(per_game_loaded) == len(per_game)


def test_export_summary_content(mock_results):
    """Test summary document content."""
    aggregated, per_game = mock_results

    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(
            aggregated_df=aggregated,
            per_game_df=per_game,
            output_dir=tmpdir,
        )

        with open(f"{tmpdir}/BACKTEST_SUMMARY.txt", "r") as f:
            summary = f.read()

        assert "Total games tested" in summary
        assert "Best performer" in summary


def test_export_schema_documentation(mock_results):
    """Test schema documentation generation."""
    aggregated, per_game = mock_results

    with tempfile.TemporaryDirectory() as tmpdir:
        export_backtest_results(
            aggregated_df=aggregated,
            per_game_df=per_game,
            output_dir=tmpdir,
        )

        with open(f"{tmpdir}/SCHEMA.md", "r") as f:
            schema = f.read()

        assert "dip_threshold" in schema
        assert "roi_pct" in schema
        assert "settlement_occurred" in schema
