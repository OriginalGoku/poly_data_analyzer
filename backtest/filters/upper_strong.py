"""Universe filter: Upper Strong favorites (open favorite price strictly above threshold)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from analytics import load_game_analytics

from backtest.contracts import GameMeta


def upper_strong(
    start_date: datetime,
    end_date: datetime,
    params: Mapping[str, Any],
) -> list[GameMeta]:
    """Filter to favorites with open price strictly above threshold.

    params keys (all optional):
      - min_open_favorite_price (default 0.85): strict lower bound
      - exclude_inferred_price_quality (default True)
      - pregame_min_cum_vol (default 5000)
      - open_anchor_stat (default "vwap")
      - open_anchor_window_min (default 5)
    """
    min_price = float(params.get("min_open_favorite_price", 0.85))
    exclude_inferred = bool(params.get("exclude_inferred_price_quality", True))
    pregame_min_cum_vol = params.get("pregame_min_cum_vol", 5000)
    open_anchor_stat = params.get("open_anchor_stat", "vwap")
    open_anchor_window_min = params.get("open_anchor_window_min", 5)

    analytics = load_game_analytics(
        data_dir=params.get("data_dir", "data"),
        pregame_min_cum_vol=pregame_min_cum_vol,
        open_anchor_stat=open_anchor_stat,
        open_anchor_window_min=open_anchor_window_min,
    )

    qualified: list[GameMeta] = []
    for _, row in analytics.iterrows():
        game_date = datetime.fromisoformat(row["date"])
        if not (start_date <= game_date <= end_date):
            continue

        if row.get("open_favorite_price", 0) <= min_price:
            continue
        if row.get("open_favorite_team") == "Tie":
            continue

        in_game_vol = row.get("in_game_notional_usdc")
        if in_game_vol is not None and in_game_vol == 0:
            continue

        price_quality = row.get("price_quality", "unknown")
        if exclude_inferred and price_quality == "inferred":
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
                open_favorite_team=row.get("open_favorite_team", ""),
            )
        )

    return qualified
