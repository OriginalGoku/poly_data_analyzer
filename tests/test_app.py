"""Tests for whale card rendering helpers in app.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dash.development.base_component import Component

from app import _build_whale_card, render_page


def _flatten_text(node):
    """Collect text content from a Dash component tree."""
    if node is None:
        return []
    if isinstance(node, (str, int, float)):
        return [str(node)]
    if isinstance(node, (list, tuple)):
        out = []
        for child in node:
            out.extend(_flatten_text(child))
        return out
    if isinstance(node, Component):
        return _flatten_text(getattr(node, "children", None))
    return []


def _collect_ids(node):
    """Collect all Dash component ids from a component tree."""
    if node is None:
        return []
    if isinstance(node, (list, tuple)):
        out = []
        for child in node:
            out.extend(_collect_ids(child))
        return out
    if isinstance(node, Component):
        ids = []
        component_id = getattr(node, "id", None)
        if component_id is not None:
            ids.append(component_id)
        ids.extend(_collect_ids(getattr(node, "children", None)))
        return ids
    return []


class TestWhaleCard:
    def test_shows_explicit_taker_bias_and_positions(self):
        whale_data = {
            "summary": {
                "whale_count": 1,
                "whale_volume": 1200,
                "whale_pct": 12.0,
                "total_volume": 10000,
            },
            "whales": [{
                "address": "0xAAAA",
                "display_addr": "0xAAAA...AAAA",
                "maker_volume": 0,
                "taker_volume": 1200,
                "total_volume": 1200,
                "trade_count": 2,
                "buy_volume": 900,
                "sell_volume": 300,
                "teams_traded": {"Lakers"},
                "positions": [{
                    "team": "Lakers",
                    "buy_volume": 900,
                    "sell_volume": 300,
                    "net_side": "BUY",
                }],
                "pct_of_total": 12.0,
                "primary_side": "BUY",
                "classification": "Directional",
                "maker_pct": 0.0,
                "taker_pct": 100.0,
                "maker_trade_stats": {"count": 0, "min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0},
                "taker_trade_stats": {"count": 2, "min": 300.0, "max": 900.0, "mean": 600.0, "median": 600.0},
            }],
        }

        card = _build_whale_card(whale_data)
        text = " ".join(_flatten_text(card))

        assert "Top Aggressors (Takers)" in text
        assert "#1" in text
        assert "Bias:" in text
        assert "BUY" in text
        assert "Lakers BUY $1,200" in text
        assert "Aggressor Vol" in text
        assert "Min" in text
        assert "Max" in text
        assert "Mean" in text
        assert "Median" in text
        assert "Trades" in text
        assert "$300" in text
        assert "$900" in text
        assert "$600" in text
        assert "2" in text

    def test_shows_passive_flow_for_maker_only_wallet(self):
        whale_data = {
            "summary": {
                "whale_count": 1,
                "whale_volume": 2500,
                "whale_pct": 25.0,
                "total_volume": 10000,
            },
            "whales": [{
                "address": "0xMMMM",
                "display_addr": "0xMMMM...MMMM",
                "maker_volume": 2500,
                "taker_volume": 0,
                "total_volume": 2500,
                "trade_count": 25,
                "buy_volume": 0,
                "sell_volume": 0,
                "teams_traded": set(),
                "positions": [],
                "pct_of_total": 25.0,
                "primary_side": "N/A",
                "classification": "Market Maker",
                "maker_pct": 100.0,
                "taker_pct": 0.0,
                "maker_trade_stats": {"count": 25, "min": 50.0, "max": 500.0, "mean": 100.0, "median": 50.0},
                "taker_trade_stats": {"count": 0, "min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0},
            }],
        }

        card = _build_whale_card(whale_data)
        text = " ".join(_flatten_text(card))

        assert "Top Liquidity (Makers)" in text
        assert "Flow:" in text
        assert "Passive" in text
        assert "Maker flow only, side not inferable" in text
        assert "Maker Vol" in text
        assert "Trades" in text
        assert "$50" in text
        assert "$500" in text
        assert "$100" in text
        assert "25" in text

    def test_excludes_market_makers_from_top_aggressors(self):
        whale_data = {
            "summary": {
                "whale_count": 2,
                "whale_volume": 5000,
                "whale_pct": 50.0,
                "total_volume": 10000,
            },
            "whales": [
                {
                    "address": "0xTAKER",
                    "display_addr": "0xTAKER...TAKR",
                    "maker_volume": 0,
                    "taker_volume": 1200,
                    "total_volume": 1200,
                    "trade_count": 4,
                    "buy_volume": 1000,
                    "sell_volume": 200,
                    "teams_traded": {"Lakers"},
                    "positions": [{
                        "team": "Lakers",
                        "buy_volume": 1000,
                        "sell_volume": 200,
                        "net_side": "BUY",
                    }],
                    "pct_of_total": 12.0,
                    "primary_side": "BUY",
                    "classification": "Directional",
                    "maker_pct": 0.0,
                    "taker_pct": 100.0,
                    "maker_trade_stats": {"count": 0, "min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0},
                    "taker_trade_stats": {"count": 4, "min": 200.0, "max": 400.0, "mean": 300.0, "median": 300.0},
                },
                {
                    "address": "0xMKR",
                    "display_addr": "0xMKR...MKR1",
                    "maker_volume": 3800,
                    "taker_volume": 2,
                    "total_volume": 3802,
                    "trade_count": 60,
                    "buy_volume": 0,
                    "sell_volume": 2,
                    "teams_traded": {"Raptors"},
                    "positions": [{
                        "team": "Raptors",
                        "buy_volume": 0,
                        "sell_volume": 2,
                        "net_side": "SELL",
                    }],
                    "pct_of_total": 38.0,
                    "primary_side": "SELL",
                    "classification": "Market Maker",
                    "maker_pct": 99.9,
                    "taker_pct": 0.1,
                    "maker_trade_stats": {"count": 59, "min": 50.0, "max": 100.0, "mean": 64.0, "median": 60.0},
                    "taker_trade_stats": {"count": 1, "min": 2.0, "max": 2.0, "mean": 2.0, "median": 2.0},
                },
            ],
        }

        card = _build_whale_card(whale_data)
        text = " ".join(_flatten_text(card))

        aggressor_section = text.split("Top Aggressors (Takers)", 1)[1].split("Top Liquidity (Makers)", 1)[0]
        assert "0xTAKER...TAKR" in aggressor_section
        assert "0xMKR...MKR1" not in aggressor_section


def test_render_page_includes_sensitivity_graphs_on_root_dashboard():
    content = render_page("/")
    ids = _collect_ids(content)

    assert "sensitivity-timeline" in ids
    assert "sensitivity-surface" in ids
    assert "discrepancy-chart" in ids
    assert "regime-transitions-chart" in ids
    assert "dip-recovery-tables" in ids
