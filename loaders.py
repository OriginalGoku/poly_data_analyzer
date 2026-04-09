"""Data loaders for Polymarket NBA game data."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def get_available_dates(data_dir: str = "data") -> list[str]:
    """Scan data directory for date directories, sorted descending."""
    p = Path(data_dir)
    if not p.is_dir():
        return []
    dates = [
        d.name for d in sorted(p.iterdir(), reverse=True)
        if d.is_dir() and _is_date_dir(d.name)
    ]
    return dates


def get_nba_games(data_dir: str, date: str) -> list[dict]:
    """Load manifest for a date, return NBA collected games."""
    manifest_path = Path(data_dir) / date / "manifest.json"
    if not manifest_path.exists():
        return []
    with open(manifest_path) as f:
        entries = json.load(f)
    return [
        g for g in entries
        if g.get("sport") == "nba" and g.get("status") == "collected"
    ]


def load_game(data_dir: str, date: str, match_id: str) -> dict:
    """Load trades and events for a single game.

    Returns dict with keys: manifest, trades_df, trades_meta, events
    """
    base = Path(data_dir) / date

    # Find manifest entry
    with open(base / "manifest.json") as f:
        entries = json.load(f)
    manifest = next((g for g in entries if g["match_id"] == match_id), None)
    if manifest is None:
        raise ValueError(f"Game {match_id} not found in {date} manifest")

    # Build token_id -> team name mapping
    token_to_team = {}
    for i, token_id in enumerate(manifest["token_ids"]):
        token_to_team[token_id] = manifest["outcomes"][i]

    # Load trades
    trades_path = base / f"{match_id}_trades.json"
    with open(trades_path) as f:
        trades_data = json.load(f)

    trades_list = trades_data["trades"]
    trades_meta = {k: v for k, v in trades_data.items() if k != "trades"}

    trades_df = pd.DataFrame(trades_list)
    trades_df["datetime"] = pd.to_datetime(trades_df["timestamp"], unit="s", utc=True)
    trades_df["team"] = trades_df["asset"].map(token_to_team)

    # Parse gamma timestamps
    gamma_start = _parse_iso(manifest.get("gamma_start_time"))
    gamma_closed = _parse_iso(manifest.get("gamma_closed_time"))

    # Load events if file exists
    events_path = base / f"{match_id}_events.json"
    events = None
    tricode_map = {}
    if events_path.exists():
        with open(events_path) as f:
            events_data = json.load(f)
        events = events_data.get("events", [])

        # Parse time_actual on each event
        for ev in events:
            ev["time_actual_dt"] = _parse_iso(ev.get("time_actual"))

        # Build tricode -> team mapping by tracking score changes
        tricode_map = _build_tricode_map(events, manifest)

    return {
        "manifest": manifest,
        "trades_df": trades_df,
        "trades_meta": trades_meta,
        "events": events,
        "tricode_map": tricode_map,
        "gamma_start": gamma_start,
        "gamma_closed": gamma_closed,
    }


def _build_tricode_map(events: list[dict], manifest: dict) -> dict:
    """Map team_tricode to away/home team name by tracking score changes."""
    tricode_map = {}
    prev_away = 0
    prev_home = 0

    for ev in events:
        tricode = ev.get("team_tricode")
        if not tricode:
            continue
        away_score = ev.get("away_score", 0) or 0
        home_score = ev.get("home_score", 0) or 0

        if away_score > prev_away and tricode not in tricode_map:
            tricode_map[tricode] = manifest["away_team"]
        elif home_score > prev_home and tricode not in tricode_map:
            tricode_map[tricode] = manifest["home_team"]

        prev_away = away_score
        prev_home = home_score

    return tricode_map


def _parse_iso(s: str | None) -> datetime | None:
    """Parse ISO timestamp string to timezone-aware datetime, or None."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt
    except (ValueError, AttributeError):
        return None


def _is_date_dir(name: str) -> bool:
    """Check if directory name matches YYYY-MM-DD pattern."""
    try:
        datetime.strptime(name, "%Y-%m-%d")
        return True
    except ValueError:
        return False
