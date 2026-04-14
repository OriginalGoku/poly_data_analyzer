"""Tests for backtest configuration."""
import pytest

from backtest.backtest_config import DipBuyBacktestConfig


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


def test_config_exit_types():
    """Test all valid exit types."""
    for exit_type in ["settlement", "reversion_to_open", "reversion_to_partial", "fixed_profit"]:
        config = DipBuyBacktestConfig(exit_type=exit_type)
        assert config.exit_type == exit_type


def test_config_dip_anchor_default():
    """dip_anchor defaults to 'open'."""
    config = DipBuyBacktestConfig()
    assert config.dip_anchor == "open"


def test_config_dip_anchor_tipoff():
    """dip_anchor can be set to 'tipoff'."""
    config = DipBuyBacktestConfig(dip_anchor="tipoff")
    assert config.dip_anchor == "tipoff"


def test_config_no_time_based_quarter_field():
    """Deleted field time_based_quarter must not exist on config."""
    config = DipBuyBacktestConfig()
    assert not hasattr(config, "time_based_quarter")


def test_config_no_time_exit_checkpoint_field():
    """Deleted field time_exit_checkpoint must not exist on config."""
    config = DipBuyBacktestConfig()
    assert not hasattr(config, "time_exit_checkpoint")


def test_config_no_duration_fields():
    """Deleted sport-duration fields must not exist on config."""
    config = DipBuyBacktestConfig()
    assert not hasattr(config, "nba_quarter_duration_min")
    assert not hasattr(config, "nhl_period_duration_min")
    assert not hasattr(config, "mlb_inning_duration_min")
