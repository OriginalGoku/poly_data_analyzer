"""Universe filter implementations registered in the global registry."""
from __future__ import annotations

from backtest.registry import UNIVERSE_FILTERS

from backtest.filters.upper_strong import upper_strong

UNIVERSE_FILTERS["upper_strong"] = upper_strong

__all__ = ["upper_strong"]
