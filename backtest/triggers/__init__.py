"""Trigger registry — register concrete trigger callables here."""
from __future__ import annotations

from backtest.registry import TRIGGERS, TRIGGER_SCHEMAS
from backtest.triggers.dip_below_anchor import dip_below_anchor, PARAM_SCHEMA as _dip_below_anchor_schema
from backtest.triggers.pct_drop_window import pct_drop_window, PARAM_SCHEMA as _pct_drop_window_schema

TRIGGERS["dip_below_anchor"] = dip_below_anchor
TRIGGERS["pct_drop_window"] = pct_drop_window

TRIGGER_SCHEMAS["dip_below_anchor"] = _dip_below_anchor_schema
TRIGGER_SCHEMAS["pct_drop_window"] = _pct_drop_window_schema

__all__ = ["dip_below_anchor", "pct_drop_window"]
