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


class TestPositions:
    def test_per_team_breakdown(self):
        trades = _make_trades([
            ("0xMKR1", "0xTKR1", "BUY", 800, "Lakers"),
            ("0xMKR1", "0xTKR1", "SELL", 300, "Celtics"),
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 1.0})
        tkr = next(w for w in result["whales"] if w["address"] == "0xTKR1")
        assert len(tkr["positions"]) == 2
        lakers = next(p for p in tkr["positions"] if p["team"] == "Lakers")
        celtics = next(p for p in tkr["positions"] if p["team"] == "Celtics")
        assert lakers["net_side"] == "BUY"
        assert lakers["buy_volume"] == 800
        assert celtics["net_side"] == "SELL"
        assert celtics["sell_volume"] == 300

    def test_maker_only_has_no_positions(self):
        trades = _make_trades([
            ("0xMKR1", "0xTKR1", "BUY", 500, "Lakers"),
        ] + [
            ("0xMKR1", f"0xT{i:04d}", "BUY", 10, "Lakers")
            for i in range(20)
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 1.0})
        mkr = next(w for w in result["whales"] if w["address"] == "0xMKR1")
        assert mkr["positions"] == []

    def test_mixed_side_position(self):
        trades = _make_trades([
            ("0xMKR1", "0xTKR1", "BUY", 500, "Lakers"),
            ("0xMKR1", "0xTKR1", "SELL", 500, "Lakers"),
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 1.0})
        tkr = next(w for w in result["whales"] if w["address"] == "0xTKR1")
        assert tkr["positions"][0]["net_side"] == "Mixed"


class TestSummary:
    def test_summary_fields(self, sample_trades):
        result = analyze_whales(sample_trades, {"whale_min_volume_pct": 1.0})
        s = result["summary"]
        assert s["whale_count"] == len(result["whales"])
        assert s["whale_volume"] > 0
        assert s["total_volume"] == sample_trades["size"].sum()
        assert s["whale_pct"] > 0

    def test_whale_pct_is_ratio_of_whale_to_total(self, sample_trades):
        result = analyze_whales(sample_trades, {"whale_min_volume_pct": 1.0})
        s = result["summary"]
        expected_pct = s["whale_volume"] / s["total_volume"] * 100
        assert abs(s["whale_pct"] - expected_pct) < 0.01


class TestTradeSizeStats:
    def test_tracks_maker_and_taker_trade_size_stats(self):
        trades = _make_trades([
            ("0xSTAT", "0xA", "BUY", 100, "Lakers"),
            ("0xSTAT", "0xB", "BUY", 300, "Lakers"),
            ("0xM1", "0xSTAT", "SELL", 200, "Lakers"),
            ("0xM2", "0xSTAT", "BUY", 400, "Celtics"),
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 0.0})
        whale = next(w for w in result["whales"] if w["address"] == "0xSTAT")

        assert whale["maker_trade_stats"] == {
            "count": 2, "min": 100.0, "max": 300.0, "mean": 200.0, "median": 200.0,
        }
        assert whale["taker_trade_stats"] == {
            "count": 2, "min": 200.0, "max": 400.0, "mean": 300.0, "median": 300.0,
        }


class TestDisplayAddr:
    def test_format(self):
        trades = _make_trades([
            ("0xabcd1234efgh5678", "0xOTHER01", "BUY", 1000, "Lakers"),
        ])
        result = analyze_whales(trades, {"whale_min_volume_pct": 0.0})
        whale = next(w for w in result["whales"] if w["address"] == "0xabcd1234efgh5678")
        assert whale["display_addr"] == "0xabcd...5678"


class TestEmptyDataFrame:
    def test_empty_df(self):
        df = pd.DataFrame(columns=["maker", "taker", "side", "size", "team"])
        result = analyze_whales(df)
        assert result["whales"] == []
        assert result["summary"]["whale_count"] == 0
        assert result["summary"]["whale_volume"] == 0
        assert result["summary"]["whale_pct"] == 0
        assert result["summary"]["total_volume"] == 0


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
