"""Tests for main_dashboard_page module-level helpers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pages.main_dashboard_page import _build_data_warning_badge


def test_thin_pregame_volume_renders_badge():
    badge = _build_data_warning_badge(
        {"pre_game_notional_usdc": 1000.0, "trade_count": 5}, 20000
    )
    assert badge is not None
    assert "1,000" in badge.children
    assert "20,000" in badge.children


def test_healthy_game_returns_none():
    badge = _build_data_warning_badge(
        {"pre_game_notional_usdc": 100000.0, "trade_count": 500}, 20000
    )
    assert badge is None


def test_missing_fields_returns_none():
    assert _build_data_warning_badge({}, 20000) is None
    assert _build_data_warning_badge({"pre_game_notional_usdc": None, "trade_count": None}, 20000) is None


def test_low_trade_count_alone_triggers_badge():
    badge = _build_data_warning_badge(
        {"pre_game_notional_usdc": 100000.0, "trade_count": 10}, 20000
    )
    assert badge is not None
