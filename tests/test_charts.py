"""Tests for pure helper functions in charts.py."""

from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from charts import _get_tipoff, _nearest_price


# --- _get_tipoff ---

class TestGetTipoff:
    def test_returns_first_event_with_time(self):
        dt = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        events = [
            {"time_actual_dt": dt},
            {"time_actual_dt": datetime(2025, 11, 14, 20, 1, 0, tzinfo=timezone.utc)},
        ]
        assert _get_tipoff(events) == dt

    def test_skips_none_timestamps(self):
        dt = datetime(2025, 11, 14, 20, 5, 0, tzinfo=timezone.utc)
        events = [
            {"time_actual_dt": None},
            {"time_actual_dt": None},
            {"time_actual_dt": dt},
        ]
        assert _get_tipoff(events) == dt

    def test_none_events(self):
        assert _get_tipoff(None) is None

    def test_empty_events(self):
        assert _get_tipoff([]) is None

    def test_all_none_timestamps(self):
        events = [{"time_actual_dt": None}, {"time_actual_dt": None}]
        assert _get_tipoff(events) is None


# --- _nearest_price ---

class TestNearestPrice:
    @pytest.fixture()
    def trades(self):
        base = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        return pd.DataFrame({
            "datetime": [base + timedelta(seconds=i * 30) for i in range(5)],
            "price": [0.50, 0.52, 0.55, 0.53, 0.51],
        })

    def test_exact_match(self, trades):
        t = trades["datetime"].iloc[2]
        assert _nearest_price(trades, t) == 0.55

    def test_within_max_gap(self, trades):
        t = trades["datetime"].iloc[1] + timedelta(seconds=10)
        result = _nearest_price(trades, t)
        assert result is not None
        # Should snap to nearest (which is iloc[1] at 10s away)
        assert result == 0.52

    def test_beyond_max_gap_falls_back_to_last_before(self, trades):
        # Timestamp well past the last trade
        t = trades["datetime"].iloc[-1] + timedelta(seconds=120)
        result = _nearest_price(trades, t)
        # Beyond 60s gap, falls back to last known price before t
        assert result == 0.51

    def test_empty_dataframe(self):
        empty = pd.DataFrame({"datetime": [], "price": []})
        assert _nearest_price(empty, datetime(2025, 1, 1, tzinfo=timezone.utc)) is None

    def test_before_all_trades_within_gap(self, trades):
        t = trades["datetime"].iloc[0] - timedelta(seconds=10)
        result = _nearest_price(trades, t)
        # Within 60s of first trade
        assert result == 0.50

    def test_before_all_trades_beyond_gap(self, trades):
        t = trades["datetime"].iloc[0] - timedelta(seconds=120)
        result = _nearest_price(trades, t)
        # Beyond gap, no trades before t => None
        assert result is None
