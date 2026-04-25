"""reversion_to_open exit: first post-trigger trade at or above anchor price."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

import pandas as pd

from backtest.contracts import Context, Exit, Trigger


def _scan(ctx: Context, trigger: Trigger, params: Mapping[str, Any], now: datetime) -> Optional[Exit]:
    if trigger.anchor_price is None:
        return None
    target = float(trigger.anchor_price)

    sliced = ctx.slice_after(trigger.trigger_time, team=trigger.team)
    if sliced.empty:
        return None

    upper = pd.Timestamp(now)
    if ctx.game_end is not None:
        upper = min(upper, ctx.game_end)
    sliced = sliced[sliced["datetime"] < upper]
    if sliced.empty:
        return None

    hits = sliced[sliced["price"] >= target]
    if hits.empty:
        return None

    row = hits.iloc[0]
    return Exit(
        exit_time=row["datetime"],
        exit_price=float(row["price"]),
        exit_kind="reversion",
        status="filled",
    )


def reversion_to_open(ctx: Context, trigger: Trigger, params: Mapping[str, Any]):
    from backtest.exits import ExitScanner
    return ExitScanner(trigger=trigger, params=params, _scan_fn=_scan)
