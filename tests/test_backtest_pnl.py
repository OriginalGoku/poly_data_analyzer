"""Tests for PnL computation."""
import pytest

from backtest_pnl import compute_trade_pnl


def test_compute_pnl_profitable_with_taker_fee():
    """Test profitable trade with taker fee."""
    entry = {"entry_price": 0.80, "entry_time": None}
    exit_ = {"exit_price": 0.82, "exit_time": None, "hold_seconds": 60}
    settlement = (1.0, "event_derived", True)

    result = compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model="taker",
        fee_pct=0.002,
        settings=None,
    )

    assert result["entry_price"] == 0.80
    assert result["exit_price"] == 0.82
    assert abs(result["gross_pnl_cents"] - 2.0) < 0.01  # (0.82 - 0.80) * 100
    # Fee: 0.82 * 0.002 * 100 = 0.164 cents
    assert abs(result["net_pnl_cents"] - 1.836) < 0.01
    assert result["roi_pct"] > 0
    assert result["hold_seconds"] == 60
    assert result["settlement_occurred"] is True
    assert abs(result["true_pnl_cents"] - 20.0) < 0.01  # (1.0 - 0.80) * 100


def test_compute_pnl_loss():
    """Test losing trade."""
    entry = {"entry_price": 0.85, "entry_time": None}
    exit_ = {"exit_price": 0.83, "exit_time": None, "hold_seconds": 120}
    settlement = (0.0, "event_derived", True)

    result = compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model="taker",
        fee_pct=0.002,
        settings=None,
    )

    assert abs(result["gross_pnl_cents"] - (-2.0)) < 0.01  # (0.83 - 0.85) * 100
    assert result["net_pnl_cents"] < -2.0  # Worse after fees
    assert result["roi_pct"] < 0
    assert abs(result["true_pnl_cents"] - (-85.0)) < 0.01  # (0.0 - 0.85) * 100


def test_compute_pnl_maker_fee():
    """Test with maker fee (0% fee)."""
    entry = {"entry_price": 0.80, "entry_time": None}
    exit_ = {"exit_price": 0.82, "exit_time": None, "hold_seconds": 60}
    settlement = None

    result = compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model="maker",
        fee_pct=0.0,
        settings=None,
    )

    assert abs(result["gross_pnl_cents"] - 2.0) < 0.01
    assert abs(result["net_pnl_cents"] - 2.0) < 0.01  # No fee cost
    assert result["fee_cost_cents"] == 0.0


def test_compute_pnl_no_settlement():
    """Test trade with no settlement."""
    entry = {"entry_price": 0.80, "entry_time": None}
    exit_ = {"exit_price": 0.82, "exit_time": None, "hold_seconds": 60}
    settlement = None

    result = compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model="taker",
        fee_pct=0.002,
        settings=None,
    )

    assert result["settlement_occurred"] is False
    assert result["settlement_method"] is None
    assert result["true_pnl_cents"] is None


def test_compute_pnl_unresolved_settlement():
    """Test trade with unresolved settlement."""
    entry = {"entry_price": 0.80, "entry_time": None}
    exit_ = {"exit_price": 0.82, "exit_time": None, "hold_seconds": 60}
    settlement = (None, "unresolved", False)

    result = compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model="taker",
        fee_pct=0.002,
        settings=None,
    )

    assert result["settlement_occurred"] is False
    assert result["settlement_method"] == "unresolved"
    assert result["true_pnl_cents"] is None


def test_compute_pnl_no_exit():
    """Test trade with no exit."""
    entry = {"entry_price": 0.80, "entry_time": None}
    exit_ = {"exit_price": None, "exit_time": None, "hold_seconds": 0}
    settlement = None

    result = compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model="taker",
        fee_pct=0.002,
        settings=None,
    )

    assert result["gross_pnl_cents"] == 0
    assert result["net_pnl_cents"] == 0
    assert result["roi_pct"] == 0


def test_compute_pnl_roi_calculation():
    """Test ROI calculation."""
    entry = {"entry_price": 0.50, "entry_time": None}
    exit_ = {"exit_price": 0.55, "exit_time": None, "hold_seconds": 300}
    settlement = None

    result = compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model="maker",  # No fee for simplicity
        fee_pct=0.0,
        settings=None,
    )

    # Gross: 0.05 * 100 = 5 cents
    # Net: 5 cents (no fee)
    # ROI: 5 / (0.50 * 100) = 5 / 50 = 0.1 = 10%
    assert abs(result["roi_pct"] - 0.1) < 0.001
