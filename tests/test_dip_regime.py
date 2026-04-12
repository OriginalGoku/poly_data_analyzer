"""Tests for regime transition and dip recovery analytics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from charts import build_dip_recovery_chart, build_regime_transitions_chart
from dip_recovery import compute_dip_recovery_intervals, load_or_compute_dip_recovery
from regime_transitions import compute_regime_transitions, load_or_compute_regime_transitions
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
            "datetime": [base + timedelta(seconds=offset) for offset, *_ in rows],
            "asset": [asset for _, asset, _, _ in rows],
            "price": [price for _, _, price, _ in rows],
            "size": [size for _, _, _, size in rows],
        }
    )


def _events(base: datetime) -> list[dict]:
    return [
        {"time_actual_dt": base, "away_score": 0, "home_score": 0, "event_type": "start", "period": 1},
        {"time_actual_dt": base + timedelta(minutes=8), "away_score": 2, "home_score": 0, "event_type": "2pt", "period": 1},
        {"time_actual_dt": base + timedelta(minutes=16), "away_score": 2, "home_score": 2, "event_type": "2pt", "period": 2},
    ]


class TestRegimeTransitions:
    def test_detects_confirmed_band_transition_and_forward_return(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.51, 10),
                (20, "away-token", 0.52, 10),
                (30, "away-token", 0.52, 10),
                (40, "away-token", 0.52, 10),
                (50, "away-token", 0.52, 10),
                (60, "away-token", 0.70, 10),
                (70, "away-token", 0.71, 10),
                (80, "away-token", 0.72, 10),
                (90, "away-token", 0.74, 10),
            ],
        )

        df = compute_regime_transitions(
            trades,
            _events(base),
            _manifest(),
            _settings(regime_min_trades_in_window=3),
        )

        assert df is not None
        assert len(df) == 1
        row = df.iloc[0]
        assert row["from_band"] == "Lean Favorite"
        assert row["to_band"] == "Upper Moderate"
        assert row["transition_direction"] == "upgrade"
        assert abs(row["forward_return_max"] - 0.04) < 1e-9
        assert bool(row["low_confidence"]) is False

    def test_cache_round_trip(self, tmp_path):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.51, 10),
                (20, "away-token", 0.52, 10),
                (30, "away-token", 0.55, 10),
                (40, "away-token", 0.56, 10),
                (50, "away-token", 0.57, 10),
                (60, "away-token", 0.70, 10),
                (70, "away-token", 0.71, 10),
                (80, "away-token", 0.72, 10),
            ],
        )

        first = load_or_compute_regime_transitions(
            tmp_path / "cache",
            "2025-01-01",
            "match-1",
            trades,
            _events(base),
            _manifest(),
            _settings(regime_min_trades_in_window=3),
        )
        second = load_or_compute_regime_transitions(
            tmp_path / "cache",
            "2025-01-01",
            "match-1",
            pd.DataFrame(),
            [],
            _manifest(),
            _settings(regime_min_trades_in_window=3),
        )

        assert first is not None
        assert second is not None
        assert len(first) == len(second)

    def test_chart_renders_grouped_bars(self):
        df = pd.DataFrame(
            [
                {
                    "transition_time": _base_time(),
                    "from_band": "Lean Favorite",
                    "to_band": "Upper Moderate",
                    "transition_label": "Lean Favorite → Upper Moderate",
                    "transition_direction": "upgrade",
                    "favorite_team": "Away",
                    "price_at_transition": 0.70,
                    "period": 1,
                    "seconds_since_tipoff": 60,
                    "time_bin": 0,
                    "forward_max_price": 0.74,
                    "forward_min_price": 0.70,
                    "forward_return_max": 0.04,
                    "forward_time_to_max_seconds": 30.0,
                    "trades_in_window": 4,
                    "low_confidence": False,
                    "schema_version": 1,
                }
            ]
        )

        fig = build_regime_transitions_chart(df)

        assert len(fig.data) == 2
        assert fig.layout.annotations[0].text == "By Quarter"
        assert fig.layout.annotations[1].text == "By Time Bucket"


class TestDipRecovery:
    def test_detects_recovered_dip_interval(self):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.08, 10),
                (20, "away-token", 0.04, 10),
                (30, "away-token", 0.03, 10),
                (40, "away-token", 0.02, 10),
                (50, "away-token", 0.06, 10),
                (60, "away-token", 0.08, 10),
            ],
        )

        df = compute_dip_recovery_intervals(
            trades,
            _events(base),
            _manifest(),
            _settings(dip_min_trades=3, dip_thresholds=(0.05,)),
        )

        assert df is not None
        assert len(df) == 1
        row = df.iloc[0]
        assert row["team"] == "Away"
        assert row["resolution"] == "recovered"
        assert row["score_at_entry"] == "0-0"
        assert row["score_difference"] == "Tied"
        assert abs(row["duration_seconds"] - 20.0) < 1e-9
        assert abs(row["entry_price"] - 0.04) < 1e-9
        assert abs(row["min_price"] - 0.02) < 1e-9
        assert abs(row["max_recovery_price"] - 0.08) < 1e-9
        assert abs(row["future_max_price"] - 0.08) < 1e-9
        assert abs(row["future_min_price"] - 0.02) < 1e-9
        assert abs(row["peak_rebound"] - 0.04) < 1e-9
        assert abs(row["time_to_peak_rebound_seconds"] - 40.0) < 1e-9
        assert abs(row["further_drawdown"] - 0.02) < 1e-9
        assert abs(row["recovery_magnitude"] - 0.06) < 1e-9

    def test_cache_round_trip(self, tmp_path):
        base = _base_time()
        trades = _trade_rows(
            base,
            [
                (10, "away-token", 0.08, 10),
                (20, "away-token", 0.04, 10),
                (30, "away-token", 0.03, 10),
                (40, "away-token", 0.02, 10),
                (50, "away-token", 0.06, 10),
                (60, "away-token", 0.08, 10),
            ],
        )

        first = load_or_compute_dip_recovery(
            tmp_path / "cache",
            "2025-01-01",
            "match-1",
            trades,
            _events(base),
            _manifest(),
            _settings(dip_min_trades=3, dip_thresholds=(0.05,)),
        )
        second = load_or_compute_dip_recovery(
            tmp_path / "cache",
            "2025-01-01",
            "match-1",
            pd.DataFrame(),
            [],
            _manifest(),
            _settings(dip_min_trades=3, dip_thresholds=(0.05,)),
        )

        assert first is not None
        assert second is not None
        assert len(first) == len(second)

    def test_chart_renders_grouped_bars(self):
        df = pd.DataFrame(
            [
                {
                    "team": "Away",
                    "threshold": 0.05,
                    "entry_time": _base_time(),
                    "exit_time": _base_time() + timedelta(seconds=40),
                    "duration_seconds": 40.0,
                    "period": 1,
                    "seconds_since_tipoff": 20,
                    "time_bin": 0,
                    "score_at_entry": "0-0",
                    "score_difference": "Tied",
                    "entry_price": 0.04,
                    "min_price": 0.02,
                    "max_recovery_price": 0.08,
                    "future_max_price": 0.08,
                    "future_min_price": 0.02,
                    "peak_rebound": 0.04,
                    "time_to_peak_rebound_seconds": 40.0,
                    "further_drawdown": 0.02,
                    "recovery_magnitude": 0.06,
                    "recovery_pct": 1.2,
                    "time_to_max_recovery_seconds": 40.0,
                    "trade_count": 3,
                    "low_confidence": False,
                    "resolution": "recovered",
                    "schema_version": 1,
                }
            ]
        )

        fig = build_dip_recovery_chart(df)

        assert len(fig.data) == 2
        assert fig.layout.annotations[0].text == "By Quarter"
        assert fig.layout.annotations[1].text == "By Time Bucket"
