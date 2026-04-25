"""dip_below_anchor trigger.

First in-game trade on the favorite token at price <= anchor - threshold.
Anchor is either the meaningful open price or the tipoff price.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from backtest.contracts import Context, Trigger


PARAM_SCHEMA = [
    {"name": "anchor", "type": "enum", "choices": ["open", "tipoff"], "default": "open", "label": "Anchor"},
    {"name": "threshold_cents", "type": "int", "default": 10, "label": "Threshold (cents)", "sweepable": True},
]


def dip_below_anchor(
    ctx: Context,
    after_time: datetime,
    params: Mapping[str, Any],
) -> Optional[Trigger]:
    anchor = params["anchor"]
    threshold_cents = int(params["threshold_cents"])

    if anchor == "open":
        anchor_price = ctx.open_prices.get(ctx.favorite_team)
    elif anchor == "tipoff":
        anchor_price = ctx.tipoff_prices.get(ctx.favorite_team)
    else:
        raise ValueError(f"Unknown anchor: {anchor!r}")

    if anchor_price is None:
        return None

    dip_level = anchor_price - threshold_cents / 100.0

    sliced = ctx.slice_after(after_time, team=ctx.favorite_team)
    if sliced.empty:
        return None

    if ctx.game_end is not None:
        sliced = sliced[sliced["datetime"] < ctx.game_end]
        if sliced.empty:
            return None

    hits = sliced[sliced["price"] <= dip_level]
    if hits.empty:
        return None

    row = hits.iloc[0]
    token_id = (
        row["token_id"] if "token_id" in row.index else ctx.game_meta.open_fav_token_id
    )
    return Trigger(
        trigger_time=row["datetime"],
        trigger_price=float(row["price"]),
        team=ctx.favorite_team,
        token_id=token_id,
        side="yes",
        anchor_price=float(anchor_price),
    )
