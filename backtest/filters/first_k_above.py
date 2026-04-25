"""Universe filter: first K post-tipoff favorite trades all >= min_price."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

import pandas as pd

from analytics import load_game_analytics
from loaders import load_game

from backtest.contracts import GameMeta


PARAM_SCHEMA = [
    {"name": "k", "type": "int", "default": 5, "label": "K (first trades)", "sweepable": True},
    {"name": "min_price", "type": "float", "default": 0.85, "label": "Min price", "sweepable": True},
    {"name": "exclude_inferred_price_quality", "type": "bool", "default": True, "label": "Exclude inferred price quality"},
    {"name": "pregame_min_cum_vol", "type": "int", "default": 5000, "label": "Pregame min cum vol"},
    {"name": "open_anchor_stat", "type": "enum", "choices": ["vwap", "median", "mean"], "default": "vwap", "label": "Open anchor stat"},
    {"name": "open_anchor_window_min", "type": "int", "default": 5, "label": "Open anchor window (min)"},
]


def _tipoff_time(events: list[dict] | None) -> Optional[pd.Timestamp]:
    if not events:
        return None
    score_events = [
        ev
        for ev in events
        if ev.get("eventType") == "score" and ev.get("time_actual_dt") is not None
    ]
    if not score_events:
        return None
    return min(ev["time_actual_dt"] for ev in score_events)


def first_k_above(
    start_date: datetime,
    end_date: datetime,
    params: Mapping[str, Any],
) -> list[GameMeta]:
    """Include games whose first K post-tipoff favorite trades are all >= min_price.

    params keys:
      - k (default 5): number of post-tipoff favorite trades to inspect
      - min_price (default 0.85): inclusive lower bound (>=)
      - exclude_inferred_price_quality (default True)
      - pregame_min_cum_vol (default 5000)
      - open_anchor_stat (default "vwap")
      - open_anchor_window_min (default 5)
      - data_dir (default "data")
    """
    k = int(params.get("k", 5))
    min_price = float(params.get("min_price", 0.85))
    exclude_inferred = bool(params.get("exclude_inferred_price_quality", True))
    pregame_min_cum_vol = params.get("pregame_min_cum_vol", 5000)
    open_anchor_stat = params.get("open_anchor_stat", "vwap")
    open_anchor_window_min = params.get("open_anchor_window_min", 5)
    data_dir = params.get("data_dir", "data")

    analytics = load_game_analytics(
        data_dir=data_dir,
        pregame_min_cum_vol=pregame_min_cum_vol,
        open_anchor_stat=open_anchor_stat,
        open_anchor_window_min=open_anchor_window_min,
    )

    qualified: list[GameMeta] = []
    for _, row in analytics.iterrows():
        game_date = datetime.fromisoformat(row["date"])
        if not (start_date <= game_date <= end_date):
            continue

        if row.get("open_favorite_team") in (None, "", "Tie"):
            continue
        price_quality = row.get("price_quality", "unknown")
        if exclude_inferred and price_quality == "inferred":
            continue
        if not row.get("has_events", False):
            continue

        try:
            game = load_game(data_dir, row["date"], row["match_id"])
        except Exception:
            continue

        trades_df = game.get("trades_df")
        events = game.get("events")
        if trades_df is None or trades_df.empty:
            continue

        tipoff = _tipoff_time(events)
        if tipoff is None:
            continue

        favorite_team = row["open_favorite_team"]
        fav_trades = trades_df[
            (trades_df["team"] == favorite_team)
            & (trades_df["datetime"] >= tipoff)
        ].sort_values("datetime")

        if len(fav_trades) < k:
            continue

        first_k = fav_trades.head(k)
        if not (first_k["price"] >= min_price).all():
            continue

        can_settle = bool(row.get("has_events", False)) and bool(
            row.get("has_final_score", False)
        )

        qualified.append(
            GameMeta(
                date=row["date"],
                match_id=row["match_id"],
                sport=row["sport"],
                open_fav_price=float(row["open_favorite_price"]),
                tipoff_fav_price=float(
                    row.get("tipoff_favorite_price", row["open_favorite_price"])
                ),
                open_fav_token_id=str(row.get("open_favorite_token_id", "")),
                can_settle=can_settle,
                price_quality=price_quality,
                open_favorite_team=favorite_team,
            )
        )

    return qualified
