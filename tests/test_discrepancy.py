"""Tests for market-score discrepancy computation and charting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from charts import build_discrepancy_intervals_chart
from discrepancy import compute_market_score_discrepancies, load_or_compute_discrepancies
from settings import ChartSettings


def _base_time() -> datetime:
    return datetime(2025, 1, 1, 19, 0, 0, tzinfo=timezone.utc)


def _manifest() -> dict:
    return {
        "token_ids": ["away-token", "home-token"],
        "outcomes": ["Away", "Home"],
    }


def _settings(**overrides) -> ChartSettings:
    return ChartSettings(**overrides)


def _trade_rows(base: datetime, rows: list[tuple[int, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": [base + timedelta(seconds=offset) for offset, _, _ in rows],
            "asset": ["away-token"] * len(rows),
            "price": [price for _, price, _ in rows],
            "size": [size for _, _, size in rows],
        }
    )


class TestDiscrepancyIntervals:
    def test_away_leading_home_favored_creates_interval(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [(10, 0.45, 10), (20, 0.44, 10), (30, 0.43, 10), (40, 0.44, 10), (50, 0.45, 10)],
        )
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=5), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
        ]

        df = compute_market_score_discrepancies(trades, events, _manifest(), _settings())

        assert df is not None
        assert len(df) == 1
        row = df.iloc[0]
        assert row["score_state"] == "away_leading"
        assert row["market_state"] == "home_favored"
        assert row["trade_count"] == 5

    def test_home_leading_away_favored_creates_interval(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [(10, 0.55, 10), (20, 0.56, 10), (30, 0.57, 10), (40, 0.56, 10), (50, 0.55, 10)],
        )
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=5), "away_score": 0, "home_score": 2, "event_type": "2pt", "period": 1},
        ]

        df = compute_market_score_discrepancies(trades, events, _manifest(), _settings())

        assert df is not None
        assert len(df) == 1
        assert df.iloc[0]["score_state"] == "home_leading"
        assert df.iloc[0]["market_state"] == "away_favored"

    def test_tied_game_inside_dead_zone_is_not_discrepancy(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [(10, 0.50, 10), (20, 0.505, 10), (30, 0.495, 10), (40, 0.50, 10), (50, 0.51, 10)],
        )
        events = [{"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1}]

        df = compute_market_score_discrepancies(trades, events, _manifest(), _settings())

        assert df is None

    def test_tied_game_outside_dead_zone_is_discrepancy(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [(10, 0.55, 10), (20, 0.54, 10), (30, 0.55, 10), (40, 0.54, 10), (50, 0.55, 10)],
        )
        events = [{"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1}]

        df = compute_market_score_discrepancies(trades, events, _manifest(), _settings())

        assert df is not None
        assert len(df) == 1
        assert df.iloc[0]["score_state"] == "tied"
        assert df.iloc[0]["market_state"] == "away_favored"

    def test_interval_ends_when_market_realigns(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, 0.45, 10),
                (20, 0.44, 10),
                (30, 0.43, 10),
                (40, 0.44, 10),
                (50, 0.45, 10),
                (60, 0.52, 10),
            ],
        )
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=5), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
        ]

        df = compute_market_score_discrepancies(trades, events, _manifest(), _settings())

        assert df is not None
        assert len(df) == 1
        assert df.iloc[0]["trade_count"] == 5

    def test_interval_ends_when_score_realigns(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, 0.45, 10),
                (20, 0.44, 10),
                (30, 0.43, 10),
                (40, 0.44, 10),
                (50, 0.45, 10),
                (70, 0.45, 10),
            ],
        )
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=5), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=55), "away_score": 2, "home_score": 3, "event_type": "3pt", "period": 1},
        ]

        df = compute_market_score_discrepancies(trades, events, _manifest(), _settings())

        assert df is not None
        assert len(df) == 1
        assert df.iloc[0]["end_score"] == "2-0"

    def test_intervals_with_fewer_than_minimum_trades_are_dropped(self):
        base = _base_time()
        trades = _trade_rows(base, [(10, 0.45, 10), (20, 0.44, 10), (30, 0.43, 10), (40, 0.44, 10)])
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=5), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
        ]

        df = compute_market_score_discrepancies(trades, events, _manifest(), _settings())

        assert df is None

    def test_cache_round_trip(self, tmp_path):
        base = _base_time()
        trades = _trade_rows(
            base,
            [(10, 0.45, 10), (20, 0.44, 10), (30, 0.43, 10), (40, 0.44, 10), (50, 0.45, 10)],
        )
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=5), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
        ]

        first = load_or_compute_discrepancies(tmp_path / "cache", "2025-01-01", "match-1", trades, events, _manifest(), _settings())
        second = load_or_compute_discrepancies(tmp_path / "cache", "2025-01-01", "match-1", pd.DataFrame(), [], _manifest(), _settings())

        assert first is not None
        assert second is not None
        assert len(first) == len(second)


class TestDiscrepancyChart:
    def test_empty_input_returns_placeholder(self):
        fig = build_discrepancy_intervals_chart(None, _manifest())

        assert len(fig.data) == 0
        assert "no discrepancy intervals" in fig.layout.annotations[0].text.lower()

    def test_chart_renders_interval_bars(self):
        base = _base_time()
        df = pd.DataFrame(
            [
                {
                    "interval_id": 1,
                    "start_time": base,
                    "end_time": base + timedelta(minutes=2),
                    "duration_seconds": 120.0,
                    "trade_count": 6,
                    "score_state": "away_leading",
                    "market_state": "home_favored",
                    "start_score": "2-0",
                    "end_score": "2-0",
                    "score_leader": "Away (Away)",
                    "market_favorite": "Home (Home)",
                    "avg_wrong_side_edge": 0.06,
                    "max_wrong_side_edge": 0.08,
                }
            ]
        )

        fig = build_discrepancy_intervals_chart(df, _manifest())

        assert len(fig.data) == 1
        assert fig.data[0].orientation == "h"
