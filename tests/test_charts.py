"""Tests for pure helper functions in charts.py."""

from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest
from plotly.subplots import make_subplots

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from charts import (
    build_charts, _get_tipoff, _get_game_end, _collect_vmarkers,
    _filter_by_min_cum_vol, _nearest_price, _add_whale_taker_overlays,
    _add_top_taker_markers, _add_aggressor_cumulative_lines, _build_subplot_figure,
    build_score_chart, build_score_diff_chart,
)


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


# --- _get_game_end ---

class TestGetGameEnd:
    def test_returns_last_event_with_time(self):
        dt1 = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        dt2 = datetime(2025, 11, 14, 22, 30, 0, tzinfo=timezone.utc)
        events = [
            {"time_actual_dt": dt1},
            {"time_actual_dt": dt2},
        ]
        assert _get_game_end(events) == dt2

    def test_skips_trailing_none_timestamps(self):
        dt = datetime(2025, 11, 14, 22, 0, 0, tzinfo=timezone.utc)
        events = [
            {"time_actual_dt": dt},
            {"time_actual_dt": None},
            {"time_actual_dt": None},
        ]
        assert _get_game_end(events) == dt

    def test_none_events(self):
        assert _get_game_end(None) is None

    def test_empty_events(self):
        assert _get_game_end([]) is None

    def test_all_none_timestamps(self):
        events = [{"time_actual_dt": None}]
        assert _get_game_end(events) is None


# --- _collect_vmarkers ---

class TestCollectVmarkers:
    def test_all_markers(self):
        ts1 = datetime(2025, 11, 14, 19, 0, tzinfo=timezone.utc)
        ts2 = datetime(2025, 11, 14, 20, 0, tzinfo=timezone.utc)
        ts3 = datetime(2025, 11, 14, 22, 0, tzinfo=timezone.utc)
        result = _collect_vmarkers(ts1, ts2, ts3)
        assert len(result) == 3
        labels = [m[3] for m in result]
        assert labels == ["Scheduled Start", "Tip-Off", "Market Close"]

    def test_no_markers(self):
        assert _collect_vmarkers(None, None, None) == []

    def test_only_tipoff(self):
        ts = datetime(2025, 11, 14, 20, 0, tzinfo=timezone.utc)
        result = _collect_vmarkers(None, ts, None)
        assert len(result) == 1
        assert result[0][3] == "Tip-Off"
        assert result[0][1] == "green"


# --- _filter_by_min_cum_vol ---

class TestFilterByMinCumVol:
    @pytest.fixture()
    def trades(self):
        base = datetime(2025, 11, 14, 18, 0, 0, tzinfo=timezone.utc)
        return pd.DataFrame({
            "datetime": [base + timedelta(minutes=i) for i in range(5)],
            "size": [100, 200, 300, 400, 500],
        })

    def test_filters_early_low_volume(self, trades):
        # Cumulative: 100, 300, 600, 1000, 1500
        result = _filter_by_min_cum_vol(trades, 600)
        assert len(result) == 3  # rows where cum >= 600
        assert result["size"].iloc[0] == 300

    def test_threshold_zero_returns_all(self, trades):
        result = _filter_by_min_cum_vol(trades, 0)
        assert len(result) == 5

    def test_threshold_never_reached_returns_all(self, trades):
        result = _filter_by_min_cum_vol(trades, 99999)
        assert len(result) == 5

    def test_empty_df(self):
        empty = pd.DataFrame({"datetime": [], "size": []})
        result = _filter_by_min_cum_vol(empty, 100)
        assert result.empty


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


# --- _add_whale_taker_overlays ---

class TestAddWhaleTakerOverlays:
    def test_adds_separate_buy_and_sell_whale_taker_traces(self):
        base = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        trades = pd.DataFrame({
            "datetime": [
                base,
                base + timedelta(seconds=30),
                base + timedelta(minutes=1),
                base + timedelta(minutes=2),
            ],
            "asset": ["away-token", "away-token", "home-token", "home-token"],
            "maker": ["0xM1", "0xM2", "0xWHALE", "0xM4"],
            "taker": ["0xWHALE", "0xWHALE", "0xT3", "0xWHALE"],
            "side": ["BUY", "SELL", "BUY", "BUY"],
            "size": [100, 200, 300, 400],
        })
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True)

        _add_whale_taker_overlays(
            fig, trades, {"0xWHALE"},
            "away-token", "home-token", "Lakers", "Celtics",
        )

        assert len(fig.data) == 3
        names = [trace.name for trace in fig.data]
        assert names == ["Lakers Whale Buy", "Lakers Whale Sell", "Celtics Whale Buy"]

        away_buy_trace = fig.data[0]
        away_sell_trace = fig.data[1]
        home_buy_trace = fig.data[2]
        assert list(away_buy_trace.y) == [100, 0, 0]
        assert list(away_sell_trace.y) == [200, 0, 0]
        assert list(home_buy_trace.y) == [0, 0, 400]
        assert "Lakers Whale Buy" in away_buy_trace.hovertemplate
        assert "Lakers Whale Sell" in away_sell_trace.hovertemplate
        assert "Celtics Whale Buy" in home_buy_trace.hovertemplate

    def test_ignores_maker_only_whale_trades(self):
        base = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        trades = pd.DataFrame({
            "datetime": [base, base + timedelta(minutes=1)],
            "asset": ["away-token", "home-token"],
            "maker": ["0xWHALE", "0xWHALE"],
            "taker": ["0xA", "0xB"],
            "side": ["BUY", "SELL"],
            "size": [100, 200],
        })
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True)

        _add_whale_taker_overlays(
            fig, trades, {"0xWHALE"},
            "away-token", "home-token", "Lakers", "Celtics",
        )

        assert len(fig.data) == 0


class TestAddTopTakerMarkers:
    def test_adds_ranked_price_markers_for_top_taker_whales(self):
        base = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        trades = pd.DataFrame({
            "datetime": [base, base + timedelta(minutes=1), base + timedelta(minutes=2)],
            "asset": ["away-token", "away-token", "home-token"],
            "maker": ["0xM1", "0xM2", "0xM3"],
            "taker": ["0xW1", "0xW2", "0xW1"],
            "side": ["BUY", "SELL", "BUY"],
            "size": [150, 250, 350],
            "price": [0.61, 0.58, 0.42],
        })
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True)
        top_taker_whales = [
            {"address": "0xW1"},
            {"address": "0xW2"},
        ]

        _add_top_taker_markers(
            fig, trades, top_taker_whales,
            "away-token", "home-token", "Lakers", "Celtics",
        )

        assert len(fig.data) == 3
        names = [trace.name for trace in fig.data]
        assert names == [
            "Lakers Top-10 Whale Buy",
            "Lakers Top-10 Whale Sell",
            "Celtics Top-10 Whale Buy",
        ]
        assert list(fig.data[0].text) == ["#1"]
        assert list(fig.data[1].text) == ["#2"]
        assert "Amount: $%{customdata[1]:,.0f}" in fig.data[0].hovertemplate
        assert "Trade: %{customdata[2]} %{customdata[3]}" in fig.data[0].hovertemplate

    def test_filters_out_small_trades_below_game_volume_threshold(self):
        base = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        trades = pd.DataFrame({
            "datetime": [base, base + timedelta(minutes=1), base + timedelta(minutes=2)],
            "asset": ["away-token", "away-token", "home-token"],
            "maker": ["0xM1", "0xM2", "0xM3"],
            "taker": ["0xW1", "0xW2", "0xW1"],
            "side": ["BUY", "SELL", "BUY"],
            "size": [2, 10, 988],
            "price": [0.61, 0.58, 0.42],
        })
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True)
        top_taker_whales = [{"address": "0xW1"}, {"address": "0xW2"}]

        _add_top_taker_markers(
            fig, trades, top_taker_whales,
            "away-token", "home-token", "Lakers", "Celtics",
        )

        # Total volume = 1000, so threshold is 2.5. The $2 trade is filtered out.
        assert len(fig.data) == 2
        names = [trace.name for trace in fig.data]
        assert names == ["Lakers Top-10 Whale Sell", "Celtics Top-10 Whale Buy"]


class TestAddAggressorCumulativeLines:
    def test_adds_ranked_team_side_cumulative_traces(self):
        base = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        trades = pd.DataFrame({
            "datetime": [base, base + timedelta(minutes=1), base + timedelta(minutes=2)],
            "asset": ["away-token", "home-token", "home-token"],
            "maker": ["0xM1", "0xM2", "0xM3"],
            "taker": ["0xW1", "0xW1", "0xW2"],
            "side": ["BUY", "SELL", "BUY"],
            "size": [100, 200, 300],
            "price": [0.61, 0.58, 0.42],
        })
        fig = make_subplots(rows=4, cols=1, shared_xaxes=True)
        top_taker_whales = [{"address": "0xW1"}, {"address": "0xW2"}]

        _add_aggressor_cumulative_lines(
            fig, trades, top_taker_whales,
            "away-token", "home-token", "Lakers", "Celtics",
        )

        assert len(fig.data) == 3
        names = [trace.name for trace in fig.data]
        assert names == ["#1 Lakers Buy", "#1 Celtics Sell", "#2 Celtics Buy"]
        assert list(fig.data[0].y) == [100]
        assert list(fig.data[1].y) == [200]
        assert list(fig.data[2].y) == [300]


class TestBuildSubplotFigure:
    def test_game_figure_adds_aggressor_cumulative_row(self):
        base = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        trades = pd.DataFrame({
            "datetime": [base, base + timedelta(minutes=1)],
            "asset": ["away-token", "home-token"],
            "maker": ["0xM1", "0xM2"],
            "taker": ["0xW1", "0xW1"],
            "side": ["BUY", "SELL"],
            "size": [500, 700],
            "price": [0.62, 0.41],
        })

        fig = _build_subplot_figure(
            trades,
            "away-token",
            "home-token",
            "Lakers",
            "Celtics",
            title="In-Game",
            vmarkers=[],
            events=None,
            tricode_map={},
            whale_addresses={"0xW1"},
            top_taker_whales=[{"address": "0xW1"}],
            whale_marker_min_trade_pct=0.0,
        )

        assert fig.layout.yaxis4.title.text == "Aggressor Cum ($)"
        assert fig.layout.xaxis4.rangeslider.visible is True

    def test_discrete_price_points_render_as_markers(self):
        base = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        trades = pd.DataFrame({
            "datetime": [base, base + timedelta(minutes=1)],
            "asset": ["away-token", "home-token"],
            "maker": ["0xM1", "0xM2"],
            "taker": ["0xT1", "0xT2"],
            "side": ["BUY", "BUY"],
            "size": [100, 200],
            "price": [0.62, 0.41],
        })

        fig = _build_subplot_figure(
            trades,
            "away-token",
            "home-token",
            "Lakers",
            "Celtics",
            title="Pre-Game",
            vmarkers=[],
            events=None,
            tricode_map={},
            discrete_price_points=True,
        )

        assert fig.data[0].mode == "markers"
        assert fig.data[1].mode == "markers"


class TestBuildChartsPregameThreshold:
    def test_pregame_cumulative_traces_keep_original_cumulative_history(self):
        base = datetime(2025, 11, 14, 18, 0, 0, tzinfo=timezone.utc)
        tipoff = base + timedelta(minutes=4)
        trades = pd.DataFrame({
            "datetime": [
                base,
                base + timedelta(minutes=1),
                base + timedelta(minutes=2),
                base + timedelta(minutes=3),
                tipoff,
            ],
            "asset": ["away-token", "home-token", "away-token", "home-token", "away-token"],
            "maker": ["0x1", "0x2", "0x3", "0x4", "0x5"],
            "taker": ["0xa", "0xb", "0xc", "0xd", "0xe"],
            "side": ["BUY", "BUY", "BUY", "SELL", "BUY"],
            "size": [100, 200, 300, 400, 500],
            "price": [0.51, 0.49, 0.52, 0.48, 0.53],
        })
        manifest = {
            "outcomes": ["Away", "Home"],
            "token_ids": ["away-token", "home-token"],
        }
        events = [{"time_actual_dt": tipoff}]

        pregame_fig, game_fig = build_charts(
            trades,
            manifest,
            events,
            tricode_map={},
            settings={"pregame_min_cum_vol": 500},
        )

        assert game_fig is not None

        total_trace = next(trace for trace in pregame_fig.data if trace.name == "Total Cum Volume")
        assert list(total_trace.y) == [600, 1000]

        away_cum_buy = next(trace for trace in pregame_fig.data if trace.name == "Away Cum Buy")
        assert list(away_cum_buy.y) == [400]

        home_cum_sell = next(trace for trace in pregame_fig.data if trace.name == "Home Cum Sell")
        assert list(home_cum_sell.y) == [400]
        assert pregame_fig.layout.yaxis3.range[0] > 0

    def test_in_game_price_hover_includes_score_lead(self):
        base = datetime(2025, 11, 14, 18, 0, 0, tzinfo=timezone.utc)
        tipoff = base + timedelta(minutes=2)
        trades = pd.DataFrame({
            "datetime": [
                base,
                base + timedelta(minutes=1),
                tipoff,
                tipoff + timedelta(minutes=1),
            ],
            "asset": ["away-token", "home-token", "away-token", "home-token"],
            "maker": ["0x1", "0x2", "0x3", "0x4"],
            "taker": ["0xa", "0xb", "0xc", "0xd"],
            "side": ["BUY", "BUY", "BUY", "BUY"],
            "size": [100, 200, 300, 400],
            "price": [0.51, 0.49, 0.54, 0.46],
        })
        manifest = {
            "outcomes": ["Away", "Home"],
            "token_ids": ["away-token", "home-token"],
        }
        events = [
            {"time_actual_dt": tipoff, "away_score": 2, "home_score": 0},
            {"time_actual_dt": tipoff + timedelta(minutes=1), "away_score": 2, "home_score": 3},
        ]

        _, game_fig = build_charts(
            trades,
            manifest,
            events,
            tricode_map={},
            settings={"pregame_min_cum_vol": 0},
        )

        assert game_fig is not None
        assert "Score Lead" in game_fig.data[0].hovertemplate
        assert list(game_fig.data[0].customdata) == ["Away +2"]
        assert list(game_fig.data[1].customdata) == ["Home +1"]


class TestBuildScoreChart:
    def test_returns_empty_figure_without_events(self):
        fig = build_score_chart(
            {"outcomes": ["Away", "Home"]},
            None,
        )

        assert len(fig.data) == 0
        assert "no events available" in fig.layout.annotations[0].text.lower()

    def test_builds_two_team_score_traces(self):
        base = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        events = [
            {
                "time_actual_dt": base,
                "away_score": 2,
                "home_score": 0,
                "event_type": "2pt",
                "description": "Away jumper",
            },
            {
                "time_actual_dt": base + timedelta(minutes=1),
                "away_score": 2,
                "home_score": 3,
                "event_type": "3pt",
                "description": "Home three",
            },
        ]

        fig = build_score_chart(
            {"outcomes": ["Away", "Home"]},
            events,
        )

        assert len(fig.data) == 2
        assert fig.data[0].name == "Away Score"
        assert fig.data[1].name == "Home Score"
        assert list(fig.data[0].y) == [2, 2]
        assert list(fig.data[1].y) == [0, 3]
        assert fig.layout.yaxis.title.text == "Score"


class TestBuildScoreDiffChart:
    def test_returns_empty_figure_without_events(self):
        fig = build_score_diff_chart(
            {"outcomes": ["Away", "Home"]},
            None,
        )

        assert len(fig.data) == 0
        assert "no events available" in fig.layout.annotations[0].text.lower()

    def test_builds_lead_bars_with_leader_colors(self):
        base = datetime(2025, 11, 14, 20, 0, 0, tzinfo=timezone.utc)
        events = [
            {
                "time_actual_dt": base,
                "away_score": 2,
                "home_score": 0,
                "event_type": "2pt",
                "description": "Away jumper",
            },
            {
                "time_actual_dt": base + timedelta(minutes=1),
                "away_score": 2,
                "home_score": 3,
                "event_type": "3pt",
                "description": "Home three",
            },
        ]

        fig = build_score_diff_chart(
            {"outcomes": ["Away", "Home"]},
            events,
        )

        assert len(fig.data) == 1
        assert list(fig.data[0].y) == [2, 1]
        assert list(fig.data[0].marker.color) == ["#1f77b4", "#ff7f0e"]
        assert fig.layout.yaxis.title.text == "Lead"
