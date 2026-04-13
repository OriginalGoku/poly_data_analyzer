"""Settlement resolution for backtest."""
from typing import Dict, Tuple

import pandas as pd


def resolve_settlement(
    manifest: Dict,
    events: pd.DataFrame,
    trades_df: pd.DataFrame,
    game_end,
    sport: str,
    settings,
) -> Tuple[float, str, bool]:
    """Resolve settlement for a game.

    Method 1 (event-derived): If events exist and final score determinable,
    compute winner and return payout (1.0 or 0.0).

    Method 2 (unresolved): If no events or missing winner, return settled=False.

    Args:
        manifest: Game manifest dict with match metadata
        events: DataFrame with game events (may be empty)
        trades_df: DataFrame with trade data
        game_end: Game end time
        sport: Sport code (e.g., "nba", "nhl", "mlb")
        settings: ChartSettings instance

    Returns:
        Tuple of (payout, method, settled)
        - payout: 1.0 if entry token wins, 0.0 if loses
        - method: "event_derived" or "unresolved"
        - settled: True if method 1 succeeded, False otherwise
    """
    if events is None or events.empty:
        return (None, "unresolved", False)

    # Try to derive final winner from events
    # For NBA: look for final score in events
    if sport == "nba":
        final_events = events[events.get("period", 0) == 4]  # Fourth quarter
        if final_events.empty:
            return (None, "unresolved", False)

        # Get final scores from last event with scores
        score_events = final_events.dropna(subset=["away_score", "home_score"])
        if score_events.empty:
            return (None, "unresolved", False)

        final_event = score_events.iloc[-1]
        away_score = final_event.get("away_score", 0)
        home_score = final_event.get("home_score", 0)

        # Determine winner
        if away_score > home_score:
            winner_token = 0  # Away team
        elif home_score > away_score:
            winner_token = 1  # Home team
        else:
            # Tie (shouldn't happen in NBA)
            return (None, "unresolved", False)

        # Determine which token was the entry (favorite)
        open_favorite_token = manifest.get("open_favorite_token", 0)
        payout = 1.0 if winner_token == open_favorite_token else 0.0

        return (payout, "event_derived", True)

    # For other sports (v1 unsupported, return unresolved)
    return (None, "unresolved", False)
