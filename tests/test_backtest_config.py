"""Tests for backtest configuration."""
import pytest

from backtest_config import DipBuyBacktestConfig


def test_config_default():
    """Test default configuration."""
    config = DipBuyBacktestConfig()
    assert config.dip_thresholds == (10, 15, 20)
    assert config.exit_type == "settlement"
    assert config.fee_model == "taker"
    assert config.sport_filter == "nba"
    assert config.fee_pct == 0.002


def test_config_custom_dip_thresholds():
    """Test custom dip thresholds."""
    config = DipBuyBacktestConfig(dip_thresholds=(5, 10, 15))
    assert config.dip_thresholds == (5, 10, 15)


def test_config_fee_model_taker():
    """Test taker fee model."""
    config = DipBuyBacktestConfig(fee_model="taker")
    assert config.fee_pct == 0.002


def test_config_fee_model_maker():
    """Test maker fee model."""
    config = DipBuyBacktestConfig(fee_model="maker")
    assert config.fee_pct == 0.0


def test_config_immutable():
    """Test that config is frozen (immutable)."""
    config = DipBuyBacktestConfig()
    with pytest.raises(AttributeError):
        config.dip_thresholds = (1, 2, 3)


def test_config_empty_dip_thresholds():
    """Test that empty dip thresholds raise error."""
    with pytest.raises(ValueError, match="dip_thresholds must be non-empty"):
        DipBuyBacktestConfig(dip_thresholds=())


def test_config_negative_profit_target():
    """Test that negative profit target raises error."""
    with pytest.raises(ValueError, match="profit_target must be >= 0"):
        DipBuyBacktestConfig(profit_target=-1)


def test_config_sport_filters():
    """Test various sport filters."""
    for sport in ["nba", "nhl", "mlb", "all"]:
        config = DipBuyBacktestConfig(sport_filter=sport)
        assert config.sport_filter == sport


def test_config_time_exits():
    """Test time-based exit checkpoints."""
    for checkpoint in ["Q1", "Q2", "Q3", "Q4", "off"]:
        config = DipBuyBacktestConfig(time_exit_checkpoint=checkpoint)
        assert config.time_exit_checkpoint == checkpoint
