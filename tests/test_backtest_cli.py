"""Tests for backtest CLI."""
import argparse
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from backtest.backtest_cli import main


@patch("backtest_cli.run_backtest_grid")
@patch("backtest_cli.export_backtest_results")
def test_cli_basic_invocation(mock_export, mock_run_grid):
    """Test basic CLI invocation with minimal arguments."""
    mock_run_grid.return_value = (MagicMock(), MagicMock())

    with patch("sys.argv", [
        "backtest_cli",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-31",
    ]):
        main()

    mock_run_grid.assert_called_once()
    mock_export.assert_called_once()
    args, kwargs = mock_run_grid.call_args
    assert kwargs["start_date"] == datetime(2024, 1, 1)
    assert kwargs["end_date"] == datetime(2024, 1, 31)


@patch("backtest_cli.run_backtest_grid")
@patch("backtest_cli.export_backtest_results")
def test_cli_custom_thresholds(mock_export, mock_run_grid):
    """Test CLI with custom dip thresholds."""
    mock_run_grid.return_value = (MagicMock(), MagicMock())

    with patch("sys.argv", [
        "backtest_cli",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-31",
        "--dip-thresholds", "5,10,15,20",
    ]):
        main()

    args, kwargs = mock_run_grid.call_args
    configs = kwargs["configs"]
    # Should have 1 exit type * 1 fee model = 1 config
    assert len(configs) == 1
    assert configs[0].dip_thresholds == (5, 10, 15, 20)


@patch("backtest_cli.run_backtest_grid")
@patch("backtest_cli.export_backtest_results")
def test_cli_multiple_exit_types(mock_export, mock_run_grid):
    """Test CLI with multiple exit types."""
    mock_run_grid.return_value = (MagicMock(), MagicMock())

    with patch("sys.argv", [
        "backtest_cli",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-31",
        "--exit-types", "settlement,profit_target",
    ]):
        main()

    args, kwargs = mock_run_grid.call_args
    configs = kwargs["configs"]
    # Should have 2 exit types * 1 fee model = 2 configs
    assert len(configs) == 2
    assert configs[0].exit_type == "settlement"
    assert configs[1].exit_type == "profit_target"


@patch("backtest_cli.run_backtest_grid")
@patch("backtest_cli.export_backtest_results")
def test_cli_multiple_fee_models(mock_export, mock_run_grid):
    """Test CLI with multiple fee models."""
    mock_run_grid.return_value = (MagicMock(), MagicMock())

    with patch("sys.argv", [
        "backtest_cli",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-31",
        "--fee-models", "taker,maker",
    ]):
        main()

    args, kwargs = mock_run_grid.call_args
    configs = kwargs["configs"]
    # Should have 1 exit type * 2 fee models = 2 configs
    assert len(configs) == 2


@patch("backtest_cli.run_backtest_grid")
@patch("backtest_cli.export_backtest_results")
def test_cli_sport_filter(mock_export, mock_run_grid):
    """Test CLI with sport filter."""
    mock_run_grid.return_value = (MagicMock(), MagicMock())

    with patch("sys.argv", [
        "backtest_cli",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-31",
        "--sport", "mlb",
    ]):
        main()

    args, kwargs = mock_run_grid.call_args
    configs = kwargs["configs"]
    assert all(cfg.sport_filter == "mlb" for cfg in configs)


@patch("backtest_cli.run_backtest_grid")
@patch("backtest_cli.export_backtest_results")
def test_cli_data_dir(mock_export, mock_run_grid):
    """Test CLI with custom data directory."""
    mock_run_grid.return_value = (MagicMock(), MagicMock())

    with patch("sys.argv", [
        "backtest_cli",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-31",
        "--data-dir", "/custom/data",
    ]):
        main()

    args, kwargs = mock_run_grid.call_args
    assert kwargs["data_dir"] == "/custom/data"


@patch("backtest_cli.run_backtest_grid")
@patch("backtest_cli.export_backtest_results")
def test_cli_output_dir(mock_export, mock_run_grid):
    """Test CLI with custom output directory."""
    mock_run_grid.return_value = (MagicMock(), MagicMock())

    with patch("sys.argv", [
        "backtest_cli",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-31",
        "--output", "/custom/output",
    ]):
        main()

    mock_export.assert_called_once()
    args, kwargs = mock_export.call_args
    assert kwargs["output_dir"] == "/custom/output"


@patch("backtest_cli.run_backtest_grid")
@patch("backtest_cli.export_backtest_results")
def test_cli_date_parsing(mock_export, mock_run_grid):
    """Test CLI date argument parsing."""
    mock_run_grid.return_value = (MagicMock(), MagicMock())

    with patch("sys.argv", [
        "backtest_cli",
        "--start-date", "2024-06-15",
        "--end-date", "2024-12-31",
    ]):
        main()

    args, kwargs = mock_run_grid.call_args
    assert kwargs["start_date"] == datetime(2024, 6, 15)
    assert kwargs["end_date"] == datetime(2024, 12, 31)


@patch("backtest_cli.run_backtest_grid")
@patch("backtest_cli.export_backtest_results")
def test_cli_complex_grid(mock_export, mock_run_grid):
    """Test CLI with complex grid of parameters."""
    mock_run_grid.return_value = (MagicMock(), MagicMock())

    with patch("sys.argv", [
        "backtest_cli",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-31",
        "--dip-thresholds", "5,10",
        "--exit-types", "settlement,profit_target",
        "--fee-models", "taker,maker",
    ]):
        main()

    args, kwargs = mock_run_grid.call_args
    configs = kwargs["configs"]
    # Should have 2 exit types * 2 fee models = 4 configs
    assert len(configs) == 4

    # Verify all combinations are present
    combinations = [(cfg.dip_thresholds, cfg.exit_type, cfg.fee_model) for cfg in configs]
    assert ((5, 10), "settlement", "taker") in [(c[0], c[1], c[2]) for c in combinations]
