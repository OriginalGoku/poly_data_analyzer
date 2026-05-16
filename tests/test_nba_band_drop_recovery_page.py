"""Smoke + integration tests for NBABandDropRecoveryPage."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from pages.nba_band_drop_recovery_page import (
    DROP_PCTS,
    NBABandDropRecoveryPage,
    _build_detail_table,
    _build_grid_table,
    _format_cell,
)
from settings import load_chart_settings


@pytest.fixture
def settings():
    from pathlib import Path
    return load_chart_settings(Path(__file__).parent.parent / "chart_settings.json")


def test_route_and_title():
    assert NBABandDropRecoveryPage.route == "/nba-band-drop-recovery"
    assert NBABandDropRecoveryPage.title == "NBA Band Drop Recovery"


def test_layout_contains_required_ids(settings):
    page = NBABandDropRecoveryPage(settings)
    layout = page.layout()
    rendered = str(layout)
    for required_id in (
        "bdr-price-quality",
        "bdr-start-date",
        "bdr-end-date",
        "bdr-min-open-fav",
        "bdr-min-n",
        "bdr-run",
        "bdr-run-summary",
        "bdr-grid-container",
        "bdr-detail-container",
    ):
        assert required_id in rendered, f"missing id {required_id!r} in layout"


def test_format_cell_rendering_rules():
    assert _format_cell({"n": 0, "rate": None}, 5) == "—"
    assert _format_cell({"n": 3, "rate": 0.5}, 5) == "50%* (3)"
    assert _format_cell({"n": 10, "rate": 0.6}, 5) == "60% (10)"
    assert _format_cell(None, 5) == "—"


def test_build_grid_table_emits_band_column():
    grid = pd.DataFrame(
        {
            10.0: [{"n": 5, "rate": 0.6}, {"n": 0, "rate": None}],
            20.0: [{"n": 2, "rate": 0.5, "low_n": True}, {"n": 0, "rate": None}],
        },
        index=pd.Index(["Upper Strong", "Lean Favorite"], name="band"),
    )
    table = _build_grid_table(grid, min_n_display=5)
    data = table.data
    assert data[0]["Band"] == "Upper Strong"
    assert data[0]["10%"] == "60% (5)"
    assert data[1]["10%"] == "—"


def test_build_detail_table_empty():
    out = _build_detail_table(pd.DataFrame())
    rendered = str(out)
    assert "No detail rows" in rendered


def test_callback_integration_with_mocked_runner(settings, monkeypatch):
    """Wire the runner mock + a minimal base-records cache, exercise the callback."""
    page = NBABandDropRecoveryPage(settings)

    # Fake base records covering 2 NBA games with valid tipoff price.
    base = pd.DataFrame(
        [
            {
                "date": "2026-01-01",
                "match_id": "g1",
                "sport": "nba",
                "price_quality": "live",
                "open_favorite_price": 0.90,
                "tipoff_favorite_price": 0.90,
                "open_interpretable_band": "Upper Strong",
            },
            {
                "date": "2026-01-02",
                "match_id": "g2",
                "sport": "nba",
                "price_quality": "live",
                "open_favorite_price": 0.70,
                "tipoff_favorite_price": 0.70,
                "open_interpretable_band": "Upper Moderate",
            },
        ]
    )

    fake_positions = pd.DataFrame(
        [
            {
                "date": "2026-01-01",
                "match_id": "g1",
                "scenario_name": "band_drop_recovery_sweep__trigger.params.drop_pct=10",
                "entry_team": "TEAM_A",
                "entry_time": datetime(2026, 1, 1, 19, 5),
                "exit_time": datetime(2026, 1, 1, 19, 15),
                "entry_price": 0.80,
                "exit_price": 0.91,
                "exit_kind": "reversion",
                "max_drawdown_cents": 2.0,
                "sweep_axis_trigger.params.drop_pct": 10.0,
            },
            {
                "date": "2026-01-02",
                "match_id": "g2",
                "scenario_name": "band_drop_recovery_sweep__trigger.params.drop_pct=20",
                "entry_team": "TEAM_B",
                "entry_time": datetime(2026, 1, 2, 19, 5),
                "exit_time": datetime(2026, 1, 2, 21, 0),
                "entry_price": 0.55,
                "exit_price": 0.55,
                "exit_kind": "forced_close",
                "max_drawdown_cents": 5.0,
                "sweep_axis_trigger.params.drop_pct": 20.0,
            },
        ]
    )

    # register_callbacks should not crash.
    from dash import Dash
    app = Dash(__name__, suppress_callback_exceptions=True)
    page.register_callbacks(app)
    assert app.callback_map  # at least one callback registered

    # Direct call to the inner helper instead of round-tripping through Dash.
    from pages.nba_band_drop_recovery_page import _run_and_render
    with patch("pages.nba_band_drop_recovery_page.load_game_analytics", return_value=base), \
         patch("pages.nba_band_drop_recovery_page.run_scenarios", return_value=(fake_positions, pd.DataFrame())):
        summary, grid_table, detail_table = _run_and_render(
            settings,
            price_quality="all",
            start_date=None,
            end_date=None,
            min_open_fav=0.50,
            min_n_display=5,
        )
    summary_str = str(summary)
    assert "NBA Games" in summary_str
    grid_rows = grid_table.data
    bands_seen = {row["Band"] for row in grid_rows}
    assert "Upper Strong" in bands_seen
    assert "Upper Moderate" in bands_seen
    upper_strong_row = next(r for r in grid_rows if r["Band"] == "Upper Strong")
    assert upper_strong_row["10%"].startswith("100")  # 1 reversion / 1
    upper_mod_row = next(r for r in grid_rows if r["Band"] == "Upper Moderate")
    assert upper_mod_row["20%"].startswith("0")  # 0 reversion / 1


def test_drop_pcts_constant_matches_spec():
    assert DROP_PCTS == (10, 20, 30, 40, 50, 60, 70, 80, 90, 95)
