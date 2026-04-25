"""Tests for the scenario-based backtest CLI."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from backtest_cli import main


def _stub_run(*args, **kwargs):
    return pd.DataFrame(), pd.DataFrame()


def test_cli_parses_scenario_flag(tmp_path):
    captured = {}

    def fake_run(scenarios, start_date, end_date, data_dir, settings=None):
        captured["scenarios"] = list(scenarios)
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["data_dir"] = data_dir
        return pd.DataFrame(), pd.DataFrame()

    with patch("backtest_cli.run", side_effect=fake_run), \
         patch("backtest_cli.export_backtest_results") as mock_export, \
         patch("sys.argv", [
             "backtest_cli",
             "--scenario", "dip_buy_favorite",
             "--start-date", "2024-01-01",
             "--end-date", "2024-01-02",
             "--data-dir", "data",
             "--output", str(tmp_path),
         ]):
        main()

    assert captured["start_date"] == datetime(2024, 1, 1)
    assert captured["end_date"] == datetime(2024, 1, 2)
    assert captured["data_dir"] == "data"
    # dip_buy_favorite has a 3-value sweep on threshold_cents
    assert len(captured["scenarios"]) == 3
    for s in captured["scenarios"]:
        assert s.name.startswith("dip_buy_favorite")
    mock_export.assert_called_once()


def test_cli_scenarios_glob(tmp_path):
    captured = {}

    def fake_run(scenarios, **kwargs):
        captured["scenarios"] = list(scenarios)
        return pd.DataFrame(), pd.DataFrame()

    with patch("backtest_cli.run", side_effect=fake_run), \
         patch("backtest_cli.export_backtest_results"), \
         patch("sys.argv", [
             "backtest_cli",
             "--scenarios-glob", "dip_buy_favorite*",
             "--start-date", "2024-01-01",
             "--end-date", "2024-01-02",
             "--output", str(tmp_path),
         ]):
        main()

    assert len(captured["scenarios"]) >= 1
    assert all(s.name.startswith("dip_buy_favorite") for s in captured["scenarios"])


def test_cli_rejects_unknown_scenario(tmp_path):
    with patch("backtest_cli.run", side_effect=_stub_run), \
         patch("backtest_cli.export_backtest_results"), \
         patch("sys.argv", [
             "backtest_cli",
             "--scenario", "does_not_exist",
             "--start-date", "2024-01-01",
             "--end-date", "2024-01-02",
             "--output", str(tmp_path),
         ]):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert "unknown scenario" in str(excinfo.value)


def test_cli_requires_scenario_or_glob(tmp_path):
    with patch("backtest_cli.run", side_effect=_stub_run), \
         patch("backtest_cli.export_backtest_results"), \
         patch("sys.argv", [
             "backtest_cli",
             "--start-date", "2024-01-01",
             "--end-date", "2024-01-02",
             "--output", str(tmp_path),
         ]):
        with pytest.raises(SystemExit):
            main()


def test_cli_unknown_glob_rejected(tmp_path):
    with patch("backtest_cli.run", side_effect=_stub_run), \
         patch("backtest_cli.export_backtest_results"), \
         patch("sys.argv", [
             "backtest_cli",
             "--scenarios-glob", "no_such_scenario_*",
             "--start-date", "2024-01-01",
             "--end-date", "2024-01-02",
             "--output", str(tmp_path),
         ]):
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert "no scenarios match" in str(excinfo.value)


def test_cli_smoke_creates_output_files(tmp_path):
    """End-to-end smoke: runner is mocked but export is real; verify output files."""
    with patch("backtest_cli.run", side_effect=_stub_run), \
         patch("sys.argv", [
             "backtest_cli",
             "--scenario", "dip_buy_favorite",
             "--start-date", "2024-01-01",
             "--end-date", "2024-01-01",
             "--output", str(tmp_path),
         ]):
        main()

    # Find the dated subfolder.
    subdirs = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert len(subdirs) == 1
    out = subdirs[0]
    assert (out / "results_aggregated.csv").exists()
    assert (out / "results_per_game.csv").exists()
