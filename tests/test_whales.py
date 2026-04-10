"""Tests for whale analysis module."""

import pandas as pd
import pytest

from whales import analyze_whales, get_whale_trades


def _make_trades(rows):
    """Build a trades DataFrame from list of (maker, taker, side, size, team) tuples."""
    return pd.DataFrame(rows, columns=["maker", "taker", "side", "size", "team"])


@pytest.fixture
def sample_trades():
    """Trades with a clear directional taker whale and a market maker."""
    return _make_trades([
        # Whale taker (0xAAAA) — aggressive buyer
        ("0xMMMM", "0xAAAA", "BUY", 1000, "Lakers"),
        ("0xMMMM", "0xAAAA", "BUY", 1000, "Lakers"),
        ("0xMMMM", "0xAAAA", "BUY", 800, "Celtics"),
        ("0xMMMM", "0xAAAA", "SELL", 200, "Lakers"),
        # Market maker (0xMMMM) — passive on all trades above, plus more
    ] + [
        ("0xMMMM", f"0xOTHER{i:02d}", "BUY", 50, "Lakers")
        for i in range(20)
    ])


class TestClassification:
    def test_directional_taker(self, sample_trades):
        result = analyze_whales(sample_trades, {"whale_min_volume_pct": 1.0})
        whale_a = next(w for w in result["whales"] if w["address"] == "0xAAAA")
        assert whale_a["classification"] == "Directional"

    def test_market_maker(self, sample_trades):
        result = analyze_whales(sample_trades, {"whale_min_volume_pct": 1.0})
        whale_m = next(w for w in result["whales"] if w["address"] == "0xMMMM")
        assert whale_m["classification"] == "Market Maker"

    def test_hybrid(self):
        trades = _make_trades([
            ("0xHYBR", "0xOTH1", "BUY", 500, "Lakers"),
            ("0xOTH2", "0xHYBR", "SELL", 600, "Lakers"),
        ] + [
            ("0xHYBR", f"0xSMALL{i:02d}", "BUY", 10, "Lakers")
            for i in range(18)
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 1.0})
        hybrid = next(w for w in result["whales"] if w["address"] == "0xHYBR")
        assert hybrid["classification"] == "Hybrid"


class TestThresholdFiltering:
    def test_min_volume_pct_filters(self):
        trades = _make_trades([
            ("0xBIG1", "0xSMAL", "BUY", 100, "Lakers"),
            ("0xTINY", "0xSMAL", "BUY", 1, "Lakers"),
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 40.0})
        addresses = {w["address"] for w in result["whales"]}
        assert "0xBIG1" in addresses
        assert "0xTINY" not in addresses

    def test_max_count_cap(self):
        trades = _make_trades([
            (f"0xW{i:04d}", "0xTAKER", "BUY", 100 * (i + 1), "Lakers")
            for i in range(15)
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 0.0, "whale_max_count": 5})
        assert len(result["whales"]) == 5


class TestSideAttribution:
    def test_buy_primary_side(self):
        trades = _make_trades([
            ("0xMKR1", "0xTKR1", "BUY", 800, "Lakers"),
            ("0xMKR1", "0xTKR1", "SELL", 100, "Lakers"),
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 1.0})
        tkr = next(w for w in result["whales"] if w["address"] == "0xTKR1")
        assert tkr["primary_side"] == "BUY"

    def test_sell_primary_side(self):
        trades = _make_trades([
            ("0xMKR1", "0xTKR1", "SELL", 800, "Lakers"),
            ("0xMKR1", "0xTKR1", "BUY", 100, "Lakers"),
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 1.0})
        tkr = next(w for w in result["whales"] if w["address"] == "0xTKR1")
        assert tkr["primary_side"] == "SELL"

    def test_mixed_primary_side(self):
        trades = _make_trades([
            ("0xMKR1", "0xTKR1", "BUY", 500, "Lakers"),
            ("0xMKR1", "0xTKR1", "SELL", 500, "Lakers"),
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 1.0})
        tkr = next(w for w in result["whales"] if w["address"] == "0xTKR1")
        assert tkr["primary_side"] == "Mixed"

    def test_maker_only_has_no_side(self):
        trades = _make_trades([
            ("0xMKR1", "0xTKR1", "BUY", 500, "Lakers"),
            ("0xMKR1", "0xTKR2", "SELL", 500, "Lakers"),
        ] + [
            ("0xMKR1", f"0xT{i:04d}", "BUY", 10, "Lakers")
            for i in range(20)
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 1.0})
        mkr = next(w for w in result["whales"] if w["address"] == "0xMKR1")
        assert mkr["primary_side"] == "N/A"


class TestEmptyDataFrame:
    def test_empty_df(self):
        df = pd.DataFrame(columns=["maker", "taker", "side", "size", "team"])
        result = analyze_whales(df)
        assert result["whales"] == []
        assert result["summary"]["whale_count"] == 0


class TestGetWhaleTrades:
    def test_filters_to_whale_trades(self):
        trades = _make_trades([
            ("0xW001", "0xOTH1", "BUY", 100, "Lakers"),
            ("0xOTH2", "0xW001", "SELL", 200, "Lakers"),
            ("0xOTH2", "0xOTH3", "BUY", 300, "Lakers"),
        ])
        result = get_whale_trades(trades, {"0xW001"})
        assert len(result) == 2
        assert 300 not in result["size"].values

    def test_empty_whale_set(self):
        trades = _make_trades([("0xA", "0xB", "BUY", 100, "Lakers")])
        result = get_whale_trades(trades, set())
        assert result.empty

    def test_empty_df(self):
        df = pd.DataFrame(columns=["maker", "taker", "side", "size", "team"])
        result = get_whale_trades(df, {"0xW001"})
        assert result.empty
