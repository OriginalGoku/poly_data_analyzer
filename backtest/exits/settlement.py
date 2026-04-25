"""Settlement exit: hold to game_end.

The scanner is a no-op — it never produces an Exit. The engine force-closes
the position at game_end and resolves settlement payout via resolve_settlement.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from backtest.contracts import Context, Exit, Trigger


def _scan(ctx: Context, trigger: Trigger, params: Mapping[str, Any], now: datetime) -> Optional[Exit]:
    return None


def settlement(ctx: Context, trigger: Trigger, params: Mapping[str, Any]):
    from backtest.exits import ExitScanner
    return ExitScanner(trigger=trigger, params=params, _scan_fn=_scan)
