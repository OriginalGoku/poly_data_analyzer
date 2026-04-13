"""Dip-buy backtest framework."""
from backtest.backtest_baselines import (
    baseline_buy_at_open,
    baseline_buy_at_tipoff,
    baseline_buy_first_ingame,
)
from backtest.backtest_config import DipBuyBacktestConfig
from backtest.backtest_export import export_backtest_results
from backtest.backtest_pnl import compute_trade_pnl
from backtest.backtest_runner import run_backtest_grid
from backtest.backtest_settlement import resolve_settlement
from backtest.backtest_single_game import backtest_single_game
from backtest.backtest_universe import filter_upper_strong_universe
from backtest.dip_entry_detection import find_dip_entry, find_exit

__all__ = [
    "DipBuyBacktestConfig",
    "filter_upper_strong_universe",
    "find_dip_entry",
    "find_exit",
    "resolve_settlement",
    "compute_trade_pnl",
    "baseline_buy_at_open",
    "baseline_buy_at_tipoff",
    "baseline_buy_first_ingame",
    "backtest_single_game",
    "run_backtest_grid",
    "export_backtest_results",
]
