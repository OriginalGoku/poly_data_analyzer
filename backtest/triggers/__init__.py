"""Trigger registry — register concrete trigger callables here."""
from __future__ import annotations

from backtest.registry import TRIGGERS
from backtest.triggers.dip_below_anchor import dip_below_anchor
from backtest.triggers.pct_drop_window import pct_drop_window

TRIGGERS["dip_below_anchor"] = dip_below_anchor
TRIGGERS["pct_drop_window"] = pct_drop_window

__all__ = ["dip_below_anchor", "pct_drop_window"]
