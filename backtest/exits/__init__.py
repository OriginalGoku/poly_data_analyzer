"""Exit registry — register concrete exit factories here.

Each exit module exports a factory `def <name>(ctx, trigger, params) -> ExitScanner`.
ExitScanner exposes `.scan(ctx, now) -> Exit | None` for the engine to drive.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Optional

from backtest.contracts import Context, Exit, Trigger
from backtest.registry import EXITS, EXIT_SCHEMAS


@dataclass(frozen=True)
class ExitScanner:
    """Stateful scanner that resolves a trigger to an Exit (or None).

    Engine calls `scan(ctx, now)` to ask whether the exit condition has
    triggered at or before `now`. Returning None means the position is
    still open; the engine force-closes at game_end.
    """
    trigger: Trigger
    params: Mapping[str, Any]
    _scan_fn: Callable[[Context, Trigger, Mapping[str, Any], datetime], Optional[Exit]]

    def scan(self, ctx: Context, now: datetime) -> Optional[Exit]:
        return self._scan_fn(ctx, self.trigger, self.params, now)


from backtest.exits.settlement import settlement, PARAM_SCHEMA as _settlement_schema  # noqa: E402
from backtest.exits.reversion_to_open import reversion_to_open, PARAM_SCHEMA as _reversion_to_open_schema  # noqa: E402
from backtest.exits.reversion_to_partial import reversion_to_partial, PARAM_SCHEMA as _reversion_to_partial_schema  # noqa: E402
from backtest.exits.fixed_profit import fixed_profit, PARAM_SCHEMA as _fixed_profit_schema  # noqa: E402
from backtest.exits.tp_sl import tp_sl, PARAM_SCHEMA as _tp_sl_schema  # noqa: E402

EXITS["settlement"] = settlement
EXITS["reversion_to_open"] = reversion_to_open
EXITS["reversion_to_partial"] = reversion_to_partial
EXITS["fixed_profit"] = fixed_profit
EXITS["tp_sl"] = tp_sl

EXIT_SCHEMAS["settlement"] = _settlement_schema
EXIT_SCHEMAS["reversion_to_open"] = _reversion_to_open_schema
EXIT_SCHEMAS["reversion_to_partial"] = _reversion_to_partial_schema
EXIT_SCHEMAS["fixed_profit"] = _fixed_profit_schema
EXIT_SCHEMAS["tp_sl"] = _tp_sl_schema

__all__ = [
    "ExitScanner",
    "settlement",
    "reversion_to_open",
    "reversion_to_partial",
    "fixed_profit",
    "tp_sl",
]
