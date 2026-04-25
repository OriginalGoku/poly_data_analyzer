"""tp_sl exit: take-profit / stop-loss / max-hold scanner.

Params:
  - take_profit_cents (int|None): TP target = trigger_price + cents/100.
  - stop_loss_cents   (int|None): SL target = trigger_price - cents/100.
  - max_hold_seconds  (int|None): deadline = trigger_time + seconds.

Priority on a single trade: TP > SL (warn on simultaneous TP/SL hit).
Across trades: first condition (in time) wins. If deadline elapses with no
TP/SL hit, the first trade at/after deadline produces a `max_hold` Exit.
"""
from __future__ import annotations

import warnings
from datetime import datetime
from typing import Any, Mapping, Optional

import pandas as pd

from backtest.contracts import Context, Exit, Trigger


def _scan(ctx: Context, trigger: Trigger, params: Mapping[str, Any], now: datetime) -> Optional[Exit]:
    tp_cents = params.get("take_profit_cents")
    sl_cents = params.get("stop_loss_cents")
    max_hold = params.get("max_hold_seconds")

    entry = float(trigger.trigger_price)
    tp = round(entry + int(tp_cents) / 100.0, 4) if tp_cents is not None else None
    sl = round(entry - int(sl_cents) / 100.0, 4) if sl_cents is not None else None
    deadline = (
        trigger.trigger_time + pd.Timedelta(seconds=int(max_hold))
        if max_hold is not None
        else None
    )

    sliced = ctx.slice_after(trigger.trigger_time, team=trigger.team)
    upper = pd.Timestamp(now)
    if ctx.game_end is not None:
        upper = min(upper, ctx.game_end)
    if not sliced.empty:
        sliced = sliced[sliced["datetime"] < upper]

    for _, row in sliced.iterrows():
        t = row["datetime"]
        p = float(row["price"])
        if deadline is not None and t >= deadline:
            return Exit(exit_time=t, exit_price=p, exit_kind="max_hold", status="filled")
        hit_tp = tp is not None and p >= tp
        hit_sl = sl is not None and p <= sl
        if hit_tp and hit_sl:
            warnings.warn(
                f"tp_sl: trade at {t} satisfies both TP ({tp}) and SL ({sl}); "
                f"resolving as take_profit (price={p}).",
                stacklevel=2,
            )
            return Exit(exit_time=t, exit_price=p, exit_kind="take_profit", status="filled")
        if hit_tp:
            return Exit(exit_time=t, exit_price=p, exit_kind="take_profit", status="filled")
        if hit_sl:
            return Exit(exit_time=t, exit_price=p, exit_kind="stop_loss", status="filled")

    return None


def tp_sl(ctx: Context, trigger: Trigger, params: Mapping[str, Any]):
    from backtest.exits import ExitScanner
    return ExitScanner(trigger=trigger, params=params, _scan_fn=_scan)
