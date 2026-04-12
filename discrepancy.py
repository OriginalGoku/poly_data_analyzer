"""Market-score discrepancy interval computation and caching."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pandas as pd

DISCREPANCY_CACHE_SCHEMA_VERSION = 3


def compute_market_score_discrepancies(
    trades_df: pd.DataFrame,
    events: list[dict] | None,
    manifest: dict,
    settings,
) -> pd.DataFrame | None:
    """Compute intervals where scoreboard state and market favorite disagree."""
    if not events:
        return None

    score_events = [
        ev for ev in events
        if ev.get("time_actual_dt") is not None
        and ev.get("away_score") is not None
        and ev.get("home_score") is not None
    ]
    if not score_events:
        return None

    away_token = manifest["token_ids"][0]
    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]
    low = float(getattr(settings, "discrepancy_dead_zone_low", 0.49))
    high = float(getattr(settings, "discrepancy_dead_zone_high", 0.51))
    min_trades = int(getattr(settings, "discrepancy_min_trades", 5))
    max_trade_gap_seconds = int(getattr(settings, "discrepancy_max_trade_gap_seconds", 120))

    away_trades = trades_df[trades_df["asset"] == away_token].sort_values("datetime").copy()
    if away_trades.empty:
        return None
    game_start = min(ev["time_actual_dt"] for ev in score_events)
    game_end = max(ev["time_actual_dt"] for ev in score_events) + timedelta(
        minutes=float(getattr(settings, "post_game_buffer_min", 10))
    )
    away_trades = away_trades[
        (away_trades["datetime"] >= game_start) & (away_trades["datetime"] <= game_end)
    ].copy()
    if away_trades.empty:
        return None

    score_df = pd.DataFrame(
        {
            "datetime": [ev["time_actual_dt"] for ev in score_events],
            "away_score": [int(ev.get("away_score") or 0) for ev in score_events],
            "home_score": [int(ev.get("home_score") or 0) for ev in score_events],
        }
    ).sort_values("datetime")
    score_df["score_state"] = score_df.apply(
        lambda row: _score_state(int(row["away_score"]), int(row["home_score"])),
        axis=1,
    )
    score_df["score_leader"] = score_df.apply(
        lambda row: _score_leader_label(
            int(row["away_score"]),
            int(row["home_score"]),
            away_team,
            home_team,
        ),
        axis=1,
    )

    aligned = pd.merge_asof(
        away_trades,
        score_df[["datetime", "away_score", "home_score", "score_state", "score_leader"]],
        on="datetime",
        direction="backward",
    )
    aligned = aligned.dropna(subset=["score_state"]).copy()
    if aligned.empty:
        return None

    aligned["away_score"] = aligned["away_score"].astype(int)
    aligned["home_score"] = aligned["home_score"].astype(int)
    aligned["market_state"] = aligned["price"].apply(lambda price: _market_state(price, low, high))
    aligned["market_favorite"] = aligned["market_state"].apply(
        lambda state: _market_favorite_label(state, away_team, home_team)
    )
    aligned["discrepancy_value"] = aligned.apply(
        lambda row: _discrepancy_value(
            row["price"],
            row["score_state"],
            row["market_state"],
        ),
        axis=1,
    )
    aligned["discrepancy_active"] = aligned["discrepancy_value"].notna()
    active = aligned[aligned["discrepancy_active"]].copy()
    if active.empty:
        return None

    active["interval_id"] = (
        (active["discrepancy_active"] != active["discrepancy_active"].shift(1))
        | (active["score_state"] != active["score_state"].shift(1))
        | (active["market_state"] != active["market_state"].shift(1))
        | ((active["datetime"] - active["datetime"].shift(1)).dt.total_seconds() > max_trade_gap_seconds)
        | ((active["datetime"] - active["datetime"].shift(1)).dt.total_seconds() < 0)
    ).cumsum()

    rows = []
    for interval_id, interval_df in active.groupby("interval_id", sort=False):
        if len(interval_df) < min_trades:
            continue
        start_row = interval_df.iloc[0]
        end_row = interval_df.iloc[-1]
        rows.append(
            {
                "interval_id": int(interval_id),
                "start_time": start_row["datetime"],
                "end_time": end_row["datetime"],
                "duration_seconds": float(
                    max((end_row["datetime"] - start_row["datetime"]).total_seconds(), 0.0)
                ),
                "trade_count": int(len(interval_df)),
                "score_state": start_row["score_state"],
                "market_state": start_row["market_state"],
                "start_score": f"{start_row['away_score']}-{start_row['home_score']}",
                "end_score": f"{end_row['away_score']}-{end_row['home_score']}",
                "score_leader": start_row["score_leader"],
                "market_favorite": start_row["market_favorite"],
                "avg_discrepancy": float(interval_df["discrepancy_value"].mean()),
                "max_discrepancy": float(interval_df["discrepancy_value"].max()),
                "schema_version": DISCREPANCY_CACHE_SCHEMA_VERSION,
            }
        )

    if not rows:
        return None
    return pd.DataFrame(rows)


def load_or_compute_discrepancies(
    cache_dir: str | Path,
    date: str,
    match_id: str,
    trades_df: pd.DataFrame,
    events: list[dict] | None,
    manifest: dict,
    settings,
) -> pd.DataFrame | None:
    """Load cached discrepancy intervals or compute and cache them."""
    cache_path = Path(cache_dir) / date / f"{match_id}_discrepancies.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text())
        if not payload:
            return None
        df = pd.DataFrame(payload)
        if _cache_has_required_columns(df):
            df["start_time"] = pd.to_datetime(df["start_time"], utc=True, format="mixed")
            df["end_time"] = pd.to_datetime(df["end_time"], utc=True, format="mixed")
            return df

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    discrepancy_df = compute_market_score_discrepancies(trades_df, events, manifest, settings)
    serialized = [] if discrepancy_df is None else _serialize_rows(discrepancy_df)
    cache_path.write_text(json.dumps(serialized, indent=2) + "\n")
    return discrepancy_df


def _score_state(away_score: int, home_score: int) -> str:
    if away_score > home_score:
        return "away_leading"
    if home_score > away_score:
        return "home_leading"
    return "tied"


def _score_leader_label(away_score: int, home_score: int, away_team: str, home_team: str) -> str:
    if away_score > home_score:
        return f"{away_team} (Away)"
    if home_score > away_score:
        return f"{home_team} (Home)"
    return "Tied"


def _market_state(away_price: float, low: float, high: float) -> str:
    if away_price < low:
        return "home_favored"
    if away_price > high:
        return "away_favored"
    return "near_even"


def _market_favorite_label(state: str, away_team: str, home_team: str) -> str:
    if state == "away_favored":
        return f"{away_team} (Away)"
    if state == "home_favored":
        return f"{home_team} (Home)"
    return "Near Even"


def _discrepancy_value(
    away_price: float,
    score_state: str,
    market_state: str,
) -> float | None:
    if score_state == "away_leading" and market_state == "home_favored":
        return float(1.0 - (2.0 * away_price))
    if score_state == "home_leading" and market_state == "away_favored":
        return float((2.0 * away_price) - 1.0)
    if score_state == "tied" and market_state == "away_favored":
        return float(away_price - 0.5)
    if score_state == "tied" and market_state == "home_favored":
        return float(0.5 - away_price)
    return None


def _serialize_rows(df: pd.DataFrame) -> list[dict]:
    records = df.to_dict("records")
    for record in records:
        record["start_time"] = pd.Timestamp(record["start_time"]).isoformat()
        record["end_time"] = pd.Timestamp(record["end_time"]).isoformat()
    return records


def _cache_has_required_columns(df: pd.DataFrame) -> bool:
    required = {
        "interval_id",
        "start_time",
        "end_time",
        "duration_seconds",
        "trade_count",
        "score_state",
        "market_state",
        "start_score",
        "end_score",
        "score_leader",
        "market_favorite",
        "avg_discrepancy",
        "max_discrepancy",
        "schema_version",
    }
    if not required.issubset(df.columns):
        return False
    return df["schema_version"].nunique() == 1 and int(df["schema_version"].iloc[0]) == DISCREPANCY_CACHE_SCHEMA_VERSION
