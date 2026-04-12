"""Market-score discrepancy interval computation and caching."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pandas as pd

DISCREPANCY_CACHE_SCHEMA_VERSION = 4


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
    aligned = aligned.dropna(subset=["score_state"]).reset_index(drop=True).copy()
    if aligned.empty:
        return None

    aligned["price"] = aligned["price"].astype(float)
    aligned["away_score"] = aligned["away_score"].astype(int)
    aligned["home_score"] = aligned["home_score"].astype(int)
    aligned["score_gap"] = (aligned["away_score"] - aligned["home_score"]).abs()
    aligned["away_price"] = aligned["price"]
    aligned["home_price"] = 1.0 - aligned["away_price"]
    aligned["market_state"] = aligned["price"].apply(lambda price: _market_state(price, low, high))
    aligned["market_favorite"] = aligned["market_state"].apply(
        lambda state: _market_favorite_label(state, away_team, home_team)
    )
    aligned["interval_type"] = aligned["score_state"].apply(
        lambda state: "tie" if state == "tied" else "lead"
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
        summary = {
            "interval_id": int(interval_id),
            "interval_type": start_row["interval_type"],
            "start_time": start_row["datetime"],
            "end_time": end_row["datetime"],
            "duration_seconds": float(
                max((end_row["datetime"] - start_row["datetime"]).total_seconds(), 0.0)
            ),
            "trade_count": int(len(interval_df)),
            "score_state": start_row["score_state"],
            "market_state": start_row["market_state"],
            "score_gap_start": int(start_row["score_gap"]),
            "start_score": f"{start_row['away_score']}-{start_row['home_score']}",
            "end_score": f"{end_row['away_score']}-{end_row['home_score']}",
            "score_leader": start_row["score_leader"],
            "market_favorite": start_row["market_favorite"],
            "initial_discrepancy": float(start_row["discrepancy_value"]),
            "avg_discrepancy": float(interval_df["discrepancy_value"].mean()),
            "max_discrepancy": float(interval_df["discrepancy_value"].max()),
        }
        window_df, score_changed = _resolution_window(aligned, int(interval_df.index[0]))
        if start_row["interval_type"] == "lead":
            summary.update(_summarize_lead_interval(start_row, window_df, score_changed))
        else:
            summary.update(_summarize_tie_interval(start_row, window_df, score_changed))
        summary["schema_version"] = DISCREPANCY_CACHE_SCHEMA_VERSION
        rows.append(summary)

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


def _resolution_window(aligned: pd.DataFrame, start_pos: int) -> tuple[pd.DataFrame, bool]:
    """Return the contiguous same-score-state window starting at start_pos."""
    start_state = aligned.iloc[start_pos]["score_state"]
    end_pos = start_pos
    score_changed = False
    for pos in range(start_pos + 1, len(aligned)):
        if aligned.iloc[pos]["score_state"] != start_state:
            score_changed = True
            break
        end_pos = pos
    return aligned.iloc[start_pos : end_pos + 1].copy(), score_changed


def _summarize_lead_interval(
    start_row: pd.Series,
    window_df: pd.DataFrame,
    score_changed: bool,
) -> dict:
    """Summarize opportunity and resolution metrics for a lead discrepancy."""
    is_away_undervalued = start_row["score_state"] == "away_leading"
    aligned_market_state = "away_favored" if is_away_undervalued else "home_favored"
    undervalued_side = start_row["score_leader"]
    price_series = window_df["away_price"] if is_away_undervalued else window_df["home_price"]
    price_start = float(price_series.iloc[0])
    price_end = float(price_series.iloc[-1])
    price_max = float(price_series.max())
    price_min = float(price_series.min())
    improvements = price_series - price_start
    flip_rows = window_df[window_df["market_state"] == aligned_market_state]
    rebalanced_rows = window_df[window_df["market_state"] == "near_even"]
    initial_discrepancy = float(start_row["discrepancy_value"])

    flip_flag = not flip_rows.empty
    time_to_flip_seconds = (
        float((flip_rows.iloc[0]["datetime"] - start_row["datetime"]).total_seconds())
        if flip_flag
        else None
    )
    if flip_flag:
        resolution_type = "market_flip"
    elif not rebalanced_rows.empty:
        resolution_type = "market_rebalanced"
    elif score_changed:
        resolution_type = "score_change"
    else:
        resolution_type = "expired_without_flip"

    return {
        "undervalued_side": undervalued_side,
        "price_start": price_start,
        "price_end": price_end,
        "price_max": price_max,
        "price_min": price_min,
        "avg_improvement": float(improvements.mean()),
        "end_improvement": float(price_end - price_start),
        "max_improvement": float(price_max - price_start),
        "max_drawdown": float(max(price_start - price_min, 0.0)),
        "flip_flag": flip_flag,
        "time_to_flip_seconds": time_to_flip_seconds,
        "correction_ratio_end": float((price_end - price_start) / initial_discrepancy),
        "correction_ratio_max": float((price_max - price_start) / initial_discrepancy),
        "resolution_type": resolution_type,
    }


def _summarize_tie_interval(
    start_row: pd.Series,
    window_df: pd.DataFrame,
    score_changed: bool,
) -> dict:
    """Summarize reversion metrics for a tie discrepancy."""
    distance_series = (window_df["away_price"] - 0.5).abs()
    distance_start = float(distance_series.iloc[0])
    distance_end = float(distance_series.iloc[-1])
    distance_min = float(distance_series.min())
    reversions = distance_start - distance_series
    dead_zone_rows = window_df[window_df["market_state"] == "near_even"]
    returned_to_dead_zone = not dead_zone_rows.empty
    time_to_dead_zone_seconds = (
        float((dead_zone_rows.iloc[0]["datetime"] - start_row["datetime"]).total_seconds())
        if returned_to_dead_zone
        else None
    )
    if returned_to_dead_zone:
        resolution_type = "returned_to_dead_zone"
    elif score_changed:
        resolution_type = "score_change"
    else:
        resolution_type = "expired_without_reversion"

    return {
        "price_start": float(start_row["away_price"]),
        "price_end": float(window_df.iloc[-1]["away_price"]),
        "distance_start": distance_start,
        "distance_end": distance_end,
        "distance_min": distance_min,
        "avg_reversion": float(reversions.mean()),
        "end_reversion": float(distance_start - distance_end),
        "max_reversion": float(distance_start - distance_min),
        "returned_to_dead_zone": returned_to_dead_zone,
        "time_to_dead_zone_seconds": time_to_dead_zone_seconds,
        "reversion_ratio_end": float((distance_start - distance_end) / distance_start),
        "reversion_ratio_max": float((distance_start - distance_min) / distance_start),
        "resolution_type": resolution_type,
    }


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
        "interval_type",
        "score_gap_start",
        "start_score",
        "end_score",
        "score_leader",
        "market_favorite",
        "initial_discrepancy",
        "avg_discrepancy",
        "max_discrepancy",
        "price_start",
        "price_end",
        "resolution_type",
        "schema_version",
    }
    if not required.issubset(df.columns):
        return False
    return df["schema_version"].nunique() == 1 and int(df["schema_version"].iloc[0]) == DISCREPANCY_CACHE_SCHEMA_VERSION
