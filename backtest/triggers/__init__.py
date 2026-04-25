"""Trigger registry — register concrete trigger callables here."""
from __future__ import annotations

from backtest.registry import TRIGGERS
from backtest.triggers.dip_below_anchor import dip_below_anchor

TRIGGERS["dip_below_anchor"] = dip_below_anchor

__all__ = ["dip_below_anchor"]
