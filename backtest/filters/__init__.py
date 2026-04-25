"""Universe filter implementations registered in the global registry."""
from __future__ import annotations

from backtest.registry import UNIVERSE_FILTERS

from backtest.filters.upper_strong import upper_strong
from backtest.filters.first_k_above import first_k_above

UNIVERSE_FILTERS["upper_strong"] = upper_strong
UNIVERSE_FILTERS["first_k_above"] = first_k_above

__all__ = ["upper_strong", "first_k_above"]
