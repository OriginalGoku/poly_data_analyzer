"""Universe filter implementations registered in the global registry."""
from __future__ import annotations

from backtest.registry import UNIVERSE_FILTERS, UNIVERSE_FILTER_SCHEMAS

from backtest.filters.upper_strong import upper_strong, PARAM_SCHEMA as _upper_strong_schema
from backtest.filters.first_k_above import first_k_above, PARAM_SCHEMA as _first_k_above_schema

UNIVERSE_FILTERS["upper_strong"] = upper_strong
UNIVERSE_FILTERS["first_k_above"] = first_k_above

UNIVERSE_FILTER_SCHEMAS["upper_strong"] = _upper_strong_schema
UNIVERSE_FILTER_SCHEMAS["first_k_above"] = _first_k_above_schema

__all__ = ["upper_strong", "first_k_above"]
