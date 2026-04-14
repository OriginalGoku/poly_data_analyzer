"""Universe filtering for backtest: Upper Strong favorites."""
from datetime import datetime
from typing import List, Tuple

from analytics import load_game_analytics


def filter_upper_strong_universe(
    start_date: datetime,
    end_date: datetime,
    data_dir: str = "data",
    exclude_inferred_price_quality: bool = True,
    pregame_min_cum_vol: float = 5000,
    open_anchor_stat: str = "vwap",
    open_anchor_window_min: int = 5,
) -> List[Tuple[str, str, str, float, float, int, bool, str]]:
    """Filter to Upper Strong favorites (open_fav_price > 0.85).

    Args:
        start_date: Filter start (inclusive)
        end_date: Filter end (inclusive)
        data_dir: Root data directory
        exclude_inferred_price_quality: If True, exclude games with price_quality="inferred"
        pregame_min_cum_vol: Min cumulative pregame volume before anchoring open
        open_anchor_stat: Aggregation method for open price (vwap/median)
        open_anchor_window_min: Window in minutes for open anchor

    Returns:
        List of tuples:
          (date, match_id, sport, open_fav_price, tipoff_fav_price,
           open_fav_token_id, can_settle_from_events, price_quality)
    """
    analytics = load_game_analytics(
        data_dir=data_dir,
        pregame_min_cum_vol=pregame_min_cum_vol,
        open_anchor_stat=open_anchor_stat,
        open_anchor_window_min=open_anchor_window_min,
    )

    qualified = []
    for _, row in analytics.iterrows():
        game_date = datetime.fromisoformat(row["date"])
        if not (start_date <= game_date <= end_date):
            continue

        # Filter: open_fav_price > 0.85 and not a tie
        if row.get("open_favorite_price", 0) <= 0.85:
            continue
        if row.get("open_favorite_team") == "Tie":
            continue

        # Optional: exclude inferred price_quality
        price_quality = row.get("price_quality", "unknown")
        if exclude_inferred_price_quality and price_quality == "inferred":
            continue

        # Determine if game can be settled from events
        has_events = row.get("has_events", False)
        has_final_score = row.get("has_final_score", False)
        can_settle = has_events and has_final_score

        qualified.append(
            (
                row["date"],
                row["match_id"],
                row["sport"],
                row["open_favorite_price"],
                row.get("tipoff_favorite_price", row["open_favorite_price"]),
                row.get("open_favorite_token_id", -1),
                can_settle,
                price_quality,
            )
        )

    return qualified
