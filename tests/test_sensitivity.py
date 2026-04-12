"""Tests for sensitivity computation, caching, and chart builders."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from charts import build_sensitivity_surface, build_sensitivity_timeline
from sensitivity import _classify_lead_bin, compute_event_sensitivity, load_or_compute_sensitivity
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


def _trade_rows(base: datetime, rows: list[tuple[int, str, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": [base + timedelta(seconds=offset) for offset, _, _, _ in rows],
            "asset": [asset for _, asset, _, _ in rows],
            "price": [price for _, _, price, _ in rows],
            "size": [size for _, _, _, size in rows],
        }
    )


def _basic_events(base: datetime) -> list[dict]:
    return [
        {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
        {"time_actual_dt": base + timedelta(seconds=60), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
        {"time_actual_dt": base + timedelta(seconds=120), "away_score": 2, "home_score": 3, "event_type": "3pt", "period": 2},
    ]


class TestComputeEventSensitivity:
    def test_basic_sensitivity_computation(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.40, 10),
                (20, "away-token", 0.40, 10),
                (70, "away-token", 0.50, 10),
                (80, "away-token", 0.50, 10),
                (130, "away-token", 0.60, 10),
                (140, "away-token", 0.60, 10),
            ],
        )

        df = compute_event_sensitivity(trades, _basic_events(base), _manifest(), _settings())

        assert df is not None
        assert len(df) == 2
        assert df["delta_price"].tolist() == pytest.approx([0.15, 0.15], rel=1e-6)
        assert df["pre_lead"].tolist() == [0, 2]
        assert df["post_lead"].tolist() == [2, 1]

    def test_lead_bin_classification(self):
        settings = _settings(sensitivity_lead_bin_close=3, sensitivity_lead_bin_moderate=7)

        assert _classify_lead_bin(0, settings) == "Close"
        assert _classify_lead_bin(3, settings) == "Close"
        assert _classify_lead_bin(4, settings) == "Moderate"
        assert _classify_lead_bin(7, settings) == "Moderate"
        assert _classify_lead_bin(8, settings) == "Blowout"

    def test_fewer_trades_than_window_fallback(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.40, 10),
                (20, "away-token", 0.40, 10),
                (70, "away-token", 0.50, 10),
                (80, "away-token", 0.50, 10),
            ],
        )
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=60), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
        ]

        df = compute_event_sensitivity(
            trades,
            events,
            _manifest(),
            _settings(sensitivity_price_window_trades=5),
        )

        assert df is not None
        row = df.iloc[0]
        assert row["trades_before_count"] == 2
        assert row["trades_after_count"] == 2
        assert row["price_before"] == pytest.approx(0.40, rel=1e-6)
        assert row["price_after"] == pytest.approx(0.50, rel=1e-6)

    def test_no_trades_after_event_gives_none_prices(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.40, 10),
                (20, "away-token", 0.40, 10),
                (70, "away-token", 0.50, 10),
                (80, "away-token", 0.50, 10),
            ],
        )
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=60), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=150), "away_score": 2, "home_score": 3, "event_type": "3pt", "period": 2},
        ]

        df = compute_event_sensitivity(trades, events, _manifest(), _settings())

        assert df is not None
        last = df.loc[df["event_time"] == base + timedelta(seconds=150)].iloc[0]
        assert pd.isna(last["price_after"])
        assert pd.isna(last["delta_price"])

    def test_no_events_returns_none(self):
        trades = _trade_rows(_base_time(), [(10, "away-token", 0.40, 10)])

        assert compute_event_sensitivity(trades, [], _manifest(), _settings()) is None

    def test_freethrow_points(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.40, 10),
                (20, "away-token", 0.40, 10),
                (70, "away-token", 0.45, 10),
                (80, "away-token", 0.45, 10),
            ],
        )
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=60), "away_score": 1, "home_score": 0, "event_type": "freethrow", "period": 1},
        ]

        df = compute_event_sensitivity(trades, events, _manifest(), _settings())

        assert df is not None
        assert df.iloc[0]["points"] == 1


class TestSensitivityCache:
    def test_cache_write_and_read_round_trip(self, tmp_path):
        base = _base_time()
        cache_dir = tmp_path / "cache"
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.40, 10),
                (20, "away-token", 0.40, 10),
                (70, "away-token", 0.50, 10),
                (80, "away-token", 0.50, 10),
            ],
        )
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=60), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
        ]

        first = load_or_compute_sensitivity(cache_dir, "2025-01-01", "match-1", trades, events, _manifest(), _settings())
        assert first is not None

        altered_trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.10, 10),
                (20, "away-token", 0.10, 10),
                (70, "away-token", 0.90, 10),
                (80, "away-token", 0.90, 10),
            ],
        )
        second = load_or_compute_sensitivity(cache_dir, "2025-01-01", "match-1", altered_trades, events, _manifest(), _settings())
        assert second is not None

        assert_frame_equal(first.reset_index(drop=True), second.reset_index(drop=True))

    def test_cache_directory_creation(self, tmp_path):
        base = _base_time()
        cache_dir = tmp_path / "missing-cache"
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.40, 10),
                (20, "away-token", 0.40, 10),
                (70, "away-token", 0.50, 10),
                (80, "away-token", 0.50, 10),
            ],
        )
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=60), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
        ]

        result = load_or_compute_sensitivity(cache_dir, "2025-01-01", "match-2", trades, events, _manifest(), _settings())

        assert result is not None
        assert (cache_dir / "2025-01-01").is_dir()
        assert (cache_dir / "2025-01-01" / "match-2_sensitivity.json").exists()

    def test_cache_read_accepts_mixed_iso_timestamp_formats(self, tmp_path):
        cache_path = tmp_path / "cache" / "2025-01-01" / "match-3_sensitivity.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            """[
  {
    "event_time": "2026-04-09T23:50:09+00:00",
    "team": "Away",
    "points": 2,
    "period": 1,
    "seconds_since_tipoff": 60,
    "pre_lead": 0,
    "post_lead": 2,
    "lead_bin": "Close",
    "time_bin": 0,
    "price_before": 0.4,
    "price_after": 0.45,
    "delta_price": 0.05,
    "trades_before_count": 5,
    "trades_after_count": 5
  },
  {
    "event_time": "2026-04-09T23:51:09.123456+00:00",
    "team": "Home",
    "points": 3,
    "period": 1,
    "seconds_since_tipoff": 120,
    "pre_lead": 2,
    "post_lead": 1,
    "lead_bin": "Close",
    "time_bin": 0,
    "price_before": 0.45,
    "price_after": 0.4,
    "delta_price": -0.05,
    "trades_before_count": 5,
    "trades_after_count": 5
  }
]"""
        )

        df = load_or_compute_sensitivity(
            tmp_path / "cache",
            "2025-01-01",
            "match-3",
            pd.DataFrame(),
            [],
            _manifest(),
            _settings(),
        )

        assert df is not None
        assert len(df) == 2
        assert str(df["event_time"].dtype).startswith("datetime64[ns, UTC]")


class TestSensitivityCharts:
    def test_timeline_empty_input_returns_placeholder(self):
        fig = build_sensitivity_timeline(None, _manifest(), [])

        assert len(fig.data) == 0
        assert "no sensitivity data available" in fig.layout.annotations[0].text.lower()

    def test_timeline_trace_count(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.40, 10),
                (20, "away-token", 0.40, 10),
                (70, "away-token", 0.50, 10),
                (80, "away-token", 0.50, 10),
                (130, "away-token", 0.60, 10),
                (140, "away-token", 0.60, 10),
            ],
        )
        sensitivity_df = compute_event_sensitivity(trades, _basic_events(base), _manifest(), _settings())

        fig = build_sensitivity_timeline(sensitivity_df, _manifest(), _basic_events(base))

        assert len(fig.data) == 2
        assert {trace.name for trace in fig.data} == {"Away", "Home"}

    def test_surface_subplot_structure(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.40, 10),
                (20, "away-token", 0.40, 10),
                (70, "away-token", 0.50, 10),
                (80, "away-token", 0.50, 10),
                (130, "away-token", 0.60, 10),
                (140, "away-token", 0.60, 10),
            ],
        )
        sensitivity_df = compute_event_sensitivity(trades, _basic_events(base), _manifest(), _settings())

        fig = build_sensitivity_surface(sensitivity_df, _manifest(), _settings())

        assert fig.layout.height == 500
        assert len(fig.layout.annotations) == 2
        assert fig.layout.annotations[0].text == "By Quarter"
        assert fig.layout.annotations[1].text == "By Time Bucket"

    def test_surface_empty_cells_produce_no_bar_for_absent_bins(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.40, 10),
                (20, "away-token", 0.40, 10),
                (70, "away-token", 0.50, 10),
                (80, "away-token", 0.50, 10),
            ],
        )
        events = [
            {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
            {"time_actual_dt": base + timedelta(seconds=60), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
        ]
        sensitivity_df = compute_event_sensitivity(trades, events, _manifest(), _settings())

        fig = build_sensitivity_surface(sensitivity_df, _manifest(), _settings())

        assert len(fig.data) == 2
        assert {trace.name for trace in fig.data} == {"Close"}
        assert "Moderate" not in {trace.name for trace in fig.data}
        assert "Blowout" not in {trace.name for trace in fig.data}
