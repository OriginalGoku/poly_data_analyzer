"""pct_drop_window trigger.

First in-game trade on the side-target token at price <= anchor * (1 - drop_pct/100),
optionally restricted to a time window relative to tipoff.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

import pandas as pd

from backtest.contracts import Context, Trigger


def pct_drop_window(
    ctx: Context,
    after_time: datetime,
    params: Mapping[str, Any],
) -> Optional[Trigger]:
    anchor = params["anchor"]
    drop_pct = float(params["drop_pct"])
    window = params.get("window_seconds_after_tipoff")

    side_target = ctx.scenario.side_target
    if side_target == "favorite":
        team = ctx.favorite_team
    elif side_target == "underdog":
        team = ctx.underdog_team
    else:
        raise ValueError(f"Unknown side_target: {side_target!r}")

    if anchor == "open":
        anchor_price = ctx.open_prices.get(team)
    elif anchor == "tipoff":
        anchor_price = ctx.tipoff_prices.get(team)
    else:
        raise ValueError(f"Unknown anchor: {anchor!r}")

    if anchor_price is None:
        return None

    target_price = anchor_price * (1.0 - drop_pct / 100.0)

    sliced = ctx.slice_after(after_time, team=team)
    if sliced.empty:
        return None

    if ctx.game_end is not None:
        sliced = sliced[sliced["datetime"] < ctx.game_end]
        if sliced.empty:
            return None

    if window is not None:
        if ctx.tipoff_time is None:
            return None
        lo, hi = window
        lo_ts = ctx.tipoff_time + timedelta(seconds=float(lo))
        hi_ts = ctx.tipoff_time + timedelta(seconds=float(hi))
        sliced = sliced[(sliced["datetime"] >= lo_ts) & (sliced["datetime"] < hi_ts)]
        if sliced.empty:
            return None

    hits = sliced[sliced["price"] <= target_price]
    if hits.empty:
        return None

    row = hits.iloc[0]
    token_id = (
        row["token_id"] if "token_id" in row.index else ctx.game_meta.open_fav_token_id
    )
    return Trigger(
        trigger_time=row["datetime"],
        trigger_price=float(row["price"]),
        team=team,
        token_id=token_id,
        side="yes",
        anchor_price=float(anchor_price),
    )
