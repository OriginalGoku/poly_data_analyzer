"""Settlement resolution for backtest."""
from typing import Dict, List, Optional, Tuple

import pandas as pd


def resolve_settlement(
    manifest: Dict,
    events: Optional[List[Dict]],
    trades_df: pd.DataFrame,
    game_end,
    sport: str,
    settings,
    entry_team: Optional[str] = None,
    open_favorite_team: Optional[str] = None,
) -> Tuple[Optional[float], str, bool]:
    """Resolve settlement for a game.

    Method 1 (event-derived): If events exist and final score determinable,
    compute winner and return payout (1.0 or 0.0).

    Method 2 (unresolved): If no events or missing winner, return settled=False.

    Args:
        manifest: Game manifest dict with match metadata
        events: List of event dicts with game events (may be None or empty)
        trades_df: DataFrame with trade data
        game_end: Game end time
        sport: Sport code (e.g., "nba", "nhl", "mlb")
        settings: ChartSettings instance
        entry_team: Team name held at entry (winner check compares against this)
        open_favorite_team: Deprecated alias for entry_team (kept until Step 19)

    Returns:
        Tuple of (payout, method, settled)
        - payout: 1.0 if entry token wins, 0.0 if loses, None if unresolved
        - method: "event_derived" or "unresolved"
        - settled: True if method 1 succeeded, False otherwise
    """
    if entry_team is not None and open_favorite_team is not None:
        raise TypeError(
            "resolve_settlement: pass either entry_team or open_favorite_team, not both"
        )
    if entry_team is None:
        entry_team = open_favorite_team
    if events is None or not events:
        return (None, "unresolved", False)

    # Try to derive final winner from events
    # For NBA: look for final score in events
    if sport == "nba":
        # Filter to fourth quarter or later (OT periods are 5+)
        final_events = [e for e in events if e.get("period", 0) >= 4]
        if not final_events:
            return (None, "unresolved", False)

        # Find last event with both scores
        final_event = None
        for event in reversed(final_events):
            if event.get("away_score") is not None and event.get("home_score") is not None:
                final_event = event
                break

        if final_event is None:
            return (None, "unresolved", False)

        away_score = final_event.get("away_score", 0)
        home_score = final_event.get("home_score", 0)

        # Determine winner team name
        away_team = manifest.get("away_team")
        home_team = manifest.get("home_team")

        if away_score > home_score:
            winner_team = away_team
        elif home_score > away_score:
            winner_team = home_team
        else:
            return (None, "unresolved", False)

        if entry_team is None or winner_team is None:
            return (None, "unresolved", False)

        payout = 1.0 if winner_team == entry_team else 0.0

        return (payout, "event_derived", True)

    # For other sports (v1 unsupported, return unresolved)
    return (None, "unresolved", False)
