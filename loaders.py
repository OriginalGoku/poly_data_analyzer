"""Data loaders for Polymarket NBA game data."""

import gzip
import json
import os
from datetime import datetime, timezone
from functools import lru_cache
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


def get_available_sports_from_manifests(data_dir: str = "data") -> list[str]:
    """Return available collected sports from manifest metadata only."""
    index = load_manifest_index(data_dir)
    if index.empty:
        return []
    return sorted(index["sport"].dropna().unique())


def get_dates_for_sport(data_dir: str, sport: str) -> list[str]:
    """Return available dates for a sport using manifest metadata only."""
    index = load_manifest_index(data_dir)
    if index.empty:
        return []
    filtered = index[index["sport"] == sport]
    return sorted(filtered["date"].dropna().unique(), reverse=True)


def get_games_for_date_and_sport(data_dir: str, date: str, sport: str) -> list[dict]:
    """Return collected games for a date+sport using manifest metadata only."""
    index = load_manifest_index(data_dir)
    if index.empty:
        return []
    filtered = index[(index["date"] == date) & (index["sport"] == sport)]
    return filtered.sort_values("label").to_dict("records")


def get_nba_games(data_dir: str, date: str) -> list[dict]:
    """Load manifest for a date, return NBA collected games."""
    return get_games_for_date_and_sport(data_dir, date, "nba")


def load_game(
    data_dir: str,
    date: str,
    match_id: str,
    outlier_settings: dict | None = None,
) -> dict:
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
    trades_path = base / f"{match_id}_trades.json.gz"
    trades_data = _read_json(trades_path)

    trades_list = trades_data["trades"]
    trades_meta = {k: v for k, v in trades_data.items() if k != "trades"}

    trades_df = pd.DataFrame(trades_list)
    trades_df["datetime"] = pd.to_datetime(trades_df["timestamp"], unit="s", utc=True)
    trades_df["team"] = trades_df["asset"].map(token_to_team)

    # Apply flash-crash outlier filter
    trades_df = _filter_flash_crashes(trades_df, outlier_settings)

    # Parse gamma timestamps
    gamma_start = _parse_iso(manifest.get("gamma_start_time"))
    gamma_closed = _parse_iso(manifest.get("gamma_closed_time"))

    # Load events if file exists
    events_path = base / f"{match_id}_events.json.gz"
    events = None
    tricode_map = {}
    if events_path.exists():
        events_data = _read_json(events_path)
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


def load_manifest_index(data_dir: str = "data") -> pd.DataFrame:
    """Load a lightweight collected-game index from manifest metadata."""
    return _load_manifest_index_cached(str(Path(data_dir).resolve()))


@lru_cache(maxsize=4)
def _load_manifest_index_cached(data_dir: str) -> pd.DataFrame:
    rows: list[dict] = []
    base = Path(data_dir)
    if not base.is_dir():
        return pd.DataFrame()

    for date_dir in sorted(base.iterdir(), reverse=True):
        if not date_dir.is_dir() or not _is_date_dir(date_dir.name):
            continue
        manifest_path = date_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        with open(manifest_path) as f:
            entries = json.load(f)
        for entry in entries:
            if entry.get("status") != "collected":
                continue
            rows.append(
                {
                    "date": date_dir.name,
                    "sport": entry.get("sport"),
                    "match_id": entry.get("match_id"),
                    "label": f"{entry.get('away_team')} @ {entry.get('home_team')}",
                }
            )

    if not rows:
        return pd.DataFrame(columns=["date", "sport", "match_id", "label"])
    return pd.DataFrame(rows)


def _filter_flash_crashes(
    trades_df: pd.DataFrame,
    settings: dict | None = None,
) -> pd.DataFrame:
    """Remove flash-crash outlier trades using bidirectional median comparison.

    A trade is marked as an outlier if BOTH:
      1. |price - backward_median| / backward_median > backward_threshold (%)
      2. |price - forward_median| / forward_median > forward_threshold (%)

    Thresholds are percentage-based so they scale across the full price range
    (0-1). The forward window skips trades within T seconds of the current trade
    so that a cluster of flash-crash fills doesn't dominate the forward median.
    """
    if settings is None:
        settings = {}

    bw = settings.get("outlier_backward_window", 20)
    fw = settings.get("outlier_forward_window", 20)
    bt = settings.get("outlier_backward_threshold", 0.75)
    ft = settings.get("outlier_forward_threshold", 0.50)
    skip_s = settings.get("outlier_forward_skip_seconds", 10)

    if bw <= 0 and fw <= 0:
        return trades_df

    trades_df = trades_df.sort_values("datetime").reset_index(drop=True)
    total_removed = 0
    max_passes = 5
    skip_delta = pd.Timedelta(seconds=skip_s)

    for _ in range(max_passes):
        outlier_mask = pd.Series(False, index=trades_df.index)

        for asset in trades_df["asset"].unique():
            asset_idx = trades_df.index[trades_df["asset"] == asset]
            asset_trades = trades_df.loc[asset_idx]
            prices = asset_trades["price"].astype(float)
            times = asset_trades["datetime"]

            if len(prices) < 2:
                continue

            backward_med = prices.rolling(window=bw, min_periods=1).median().shift(1)
            backward_pct_dev = ((prices - backward_med) / backward_med).abs()

            backward_suspects = backward_pct_dev > bt
            if not backward_suspects.any():
                continue

            suspect_indices = asset_idx[backward_suspects.values]
            for idx in suspect_indices:
                t = times.loc[idx]
                future = asset_trades[(times.index > idx) & (times >= t + skip_delta)]
                if len(future) < 1:
                    continue
                forward_prices = future["price"].astype(float).iloc[:fw]
                fwd_med = forward_prices.median()
                fwd_pct_dev = abs(prices.loc[idx] - fwd_med) / fwd_med if fwd_med > 0 else 0
                if fwd_pct_dev > ft:
                    outlier_mask.loc[idx] = True

        n_removed = outlier_mask.sum()
        if n_removed == 0:
            break
        total_removed += n_removed
        trades_df = trades_df[~outlier_mask].reset_index(drop=True)

    if total_removed > 0:
        import logging
        logging.getLogger(__name__).info(
            "Flash-crash filter removed %d trades", total_removed
        )

    return trades_df


def _read_json(path: Path) -> dict:
    """Read a JSON file, auto-detecting gzip by .gz suffix."""
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


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


def _derive_nba_final_score(events: list[dict] | None) -> tuple[int, int] | None:
    """Return the final away/home score from the last NBA event."""
    if not events:
        return None
    last_event = events[-1] or {}
    away_score = last_event.get("away_score")
    home_score = last_event.get("home_score")
    if away_score is None or home_score is None:
        return None
    return int(away_score), int(home_score)


def _derive_nba_final_winner(manifest: dict, events: list[dict] | None) -> str | None:
    """Derive the NBA winner from the last event's score."""
    final_score = _derive_nba_final_score(events)
    if final_score is None:
        return None
    away_score, home_score = final_score
    if away_score == home_score:
        return None
    if away_score > home_score:
        return manifest.get("away_team")
    return manifest.get("home_team")


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
