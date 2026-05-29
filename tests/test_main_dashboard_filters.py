"""Pure-function tests for the main dashboard bucket + threshold filter helper."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pages.main_dashboard_page import _apply_bucket_and_threshold


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _row(
    match_id: str,
    *,
    open_band: str = "Upper Strong",
    tipoff_band: str | None = "Upper Strong",
    tipoff_available: bool = True,
    open_fav: str = "A",
    tipoff_fav: str | None = "A",
    away_max: float | None = 0.90,
    home_max: float | None = 0.50,
    away_team: str = "A",
    home_team: str = "H",
) -> dict:
    return {
        "match_id": match_id,
        "date": "2026-04-10",
        "label": f"{away_team} @ {home_team}",
        "away_team": away_team,
        "home_team": home_team,
        "open_interpretable_band": open_band,
        "tipoff_interpretable_band": tipoff_band,
        "tipoff_available": tipoff_available,
        "open_favorite_team": open_fav,
        "tipoff_favorite_team": tipoff_fav,
        "away_in_game_max_price": away_max,
        "home_in_game_max_price": home_max,
    }


def test_bucket_all_returns_all_rows():
    df = _frame([_row("g1"), _row("g2", open_band="Lower Strong")])
    out = _apply_bucket_and_threshold(df, anchor="open", bucket="all", threshold_on=False, threshold_value=None)
    assert set(out["match_id"]) == {"g1", "g2"}


def test_open_anchor_band_filter():
    df = _frame([_row("g1"), _row("g2", open_band="Lower Strong")])
    out = _apply_bucket_and_threshold(df, anchor="open", bucket="Upper Strong", threshold_on=False, threshold_value=None)
    assert list(out["match_id"]) == ["g1"]


def test_tipoff_anchor_drops_unavailable():
    df = _frame([
        _row("g1"),
        _row("g2", tipoff_available=False),
    ])
    out = _apply_bucket_and_threshold(df, anchor="tipoff", bucket="all", threshold_on=False, threshold_value=None)
    assert list(out["match_id"]) == ["g1"]


def test_tipoff_anchor_uses_tipoff_band():
    df = _frame([
        _row("g1", tipoff_band="Lower Strong"),
        _row("g2", tipoff_band="Upper Strong"),
    ])
    out = _apply_bucket_and_threshold(df, anchor="tipoff", bucket="Lower Strong", threshold_on=False, threshold_value=None)
    assert list(out["match_id"]) == ["g1"]


def test_threshold_filters_open_favorite_at_or_above():
    df = _frame([
        _row("g1", away_max=0.95),    # A is favorite, 0.95 < 0.97 → keep
        _row("g2", away_max=0.97),    # 0.97 >= 0.97 → drop
        _row("g3", away_max=0.99),    # drop
    ])
    out = _apply_bucket_and_threshold(df, anchor="open", bucket="all", threshold_on=True, threshold_value=0.97)
    assert list(out["match_id"]) == ["g1"]


def test_threshold_preserves_nan_extremes():
    df = _frame([_row("g1", away_max=None, home_max=None)])
    out = _apply_bucket_and_threshold(df, anchor="open", bucket="all", threshold_on=True, threshold_value=0.97)
    assert list(out["match_id"]) == ["g1"]


def test_threshold_off_returns_all():
    df = _frame([_row("g1", away_max=0.99)])
    out = _apply_bucket_and_threshold(df, anchor="open", bucket="all", threshold_on=False, threshold_value=0.97)
    assert list(out["match_id"]) == ["g1"]


def test_threshold_uses_tipoff_favorite_when_anchor_tipoff():
    """A is open-favorite (away) but H is tipoff-favorite (home). At anchor=tipoff,
    threshold must check home_in_game_max_price, not away."""
    df = _frame([
        _row("g1", open_fav="A", tipoff_fav="H", away_max=0.99, home_max=0.40),
    ])
    out = _apply_bucket_and_threshold(df, anchor="tipoff", bucket="all", threshold_on=True, threshold_value=0.97)
    assert list(out["match_id"]) == ["g1"]  # home_max 0.40 < 0.97 → keep


def test_empty_input_returns_empty():
    df = pd.DataFrame()
    out = _apply_bucket_and_threshold(df, anchor="open", bucket="Upper Strong", threshold_on=True, threshold_value=0.97)
    assert out.empty
