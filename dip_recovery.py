"""Absolute-threshold dip interval detection and caching."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


DIP_RECOVERY_CACHE_SCHEMA_VERSION = 1


def compute_dip_recovery_intervals(
    trades_df: pd.DataFrame,
    events: list[dict] | None,
    manifest: dict,
    settings,
) -> pd.DataFrame | None:
    """Detect in-game token price dips below absolute thresholds."""
    if not events:
        return None

    score_events = [
        event
        for event in events
        if event.get("time_actual_dt") is not None
        and event.get("away_score") is not None
        and event.get("home_score") is not None
    ]
    if not score_events:
        return None

    tipoff_time = min(event["time_actual_dt"] for event in score_events)
    game_end = max(event["time_actual_dt"] for event in score_events) + pd.Timedelta(
        minutes=float(getattr(settings, "post_game_buffer_min", 10))
    )
    thresholds = tuple(float(value) for value in getattr(settings, "dip_thresholds", (0.05, 0.04, 0.03, 0.02)))
    min_trades = max(int(getattr(settings, "dip_min_trades", 3)), 1)
    max_gap_seconds = int(getattr(settings, "dip_max_trade_gap_seconds", 120))

    score_df = pd.DataFrame(
        {
            "datetime": [event["time_actual_dt"] for event in score_events],
            "period": [int(event.get("period") or 0) for event in score_events],
            "away_score": [int(event.get("away_score") or 0) for event in score_events],
            "home_score": [int(event.get("home_score") or 0) for event in score_events],
        }
    ).sort_values("datetime")
    score_df["datetime"] = (
        pd.to_datetime(score_df["datetime"], utc=True)
        .astype("datetime64[ns, UTC]")
    )

    rows: list[dict] = []
    for token_id, team in zip(manifest["token_ids"], manifest["outcomes"]):
        team_trades = trades_df[
            (trades_df["asset"] == token_id)
            & (trades_df["datetime"] >= tipoff_time)
            & (trades_df["datetime"] <= game_end)
        ].sort_values("datetime").copy()
        if team_trades.empty:
            continue
        team_trades["datetime"] = (
            pd.to_datetime(team_trades["datetime"], utc=True)
            .astype("datetime64[ns, UTC]")
        )

        aligned = pd.merge_asof(team_trades, score_df, on="datetime", direction="backward")
        aligned = aligned.dropna(subset=["period"]).reset_index(drop=True)
        if aligned.empty:
            continue

        aligned["price"] = aligned["price"].astype(float)
        aligned["seconds_since_tipoff"] = (
            aligned["datetime"] - tipoff_time
        ).dt.total_seconds().astype(int)
        aligned["time_bin"] = aligned["seconds_since_tipoff"] // 360

        for threshold in thresholds:
            threshold_rows = _compute_threshold_rows(
                aligned,
                team,
                threshold,
                min_trades,
                max_gap_seconds,
                game_end,
                manifest,
            )
            rows.extend(threshold_rows)

    if not rows:
        return None
    return pd.DataFrame(rows)


def load_or_compute_dip_recovery(
    cache_dir: str | Path,
    date: str,
    match_id: str,
    trades_df: pd.DataFrame,
    events: list[dict] | None,
    manifest: dict,
    settings,
) -> pd.DataFrame | None:
    """Load cached dip recovery intervals or compute and cache them."""
    cache_path = Path(cache_dir) / date / f"{match_id}_dip_recovery.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text())
        if not payload:
            return None
        df = pd.DataFrame(payload)
        if _cache_has_required_columns(df):
            df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True, format="mixed")
            df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True, format="mixed")
            return df

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    dip_df = compute_dip_recovery_intervals(trades_df, events, manifest, settings)
    serialized = [] if dip_df is None else _serialize_rows(dip_df)
    cache_path.write_text(json.dumps(serialized, indent=2) + "\n")
    return dip_df


def _compute_threshold_rows(
    aligned: pd.DataFrame,
    team: str,
    threshold: float,
    min_trades: int,
    max_gap_seconds: int,
    game_end: pd.Timestamp,
    manifest: dict,
) -> list[dict]:
    below = aligned["price"] <= threshold
    interval_id = (
        (below != below.shift(1))
        | (aligned["datetime"].diff().dt.total_seconds().fillna(0) > max_gap_seconds)
        | (aligned["datetime"].diff().dt.total_seconds().fillna(0) < 0)
    ).cumsum()
    working = aligned.assign(below_threshold=below, interval_id=interval_id)

    rows: list[dict] = []
    for _, interval_df in working[working["below_threshold"]].groupby("interval_id", sort=False):
        if len(interval_df) < min_trades:
            continue
        start_idx = int(interval_df.index[0])
        end_idx = int(interval_df.index[-1])
        start_row = aligned.loc[start_idx]
        last_row = aligned.loc[end_idx]
        next_row = aligned.loc[end_idx + 1] if end_idx + 1 < len(aligned) else None
        if next_row is not None and float(next_row["price"]) > threshold:
            exit_time = next_row["datetime"]
            resolution = "recovered"
        elif next_row is None and last_row["datetime"] >= game_end - pd.Timedelta(seconds=max_gap_seconds):
            exit_time = last_row["datetime"]
            resolution = "game_ended"
        else:
            exit_time = last_row["datetime"]
            resolution = "remained_below"

        forward_window = aligned[aligned["datetime"] >= start_row["datetime"]].copy()
        if forward_window.empty:
            continue

        max_row = forward_window.loc[forward_window["price"].idxmax()]
        min_row = forward_window.loc[forward_window["price"].idxmin()]
        gaps = forward_window["datetime"].diff().dt.total_seconds().dropna()
        entry_price = float(start_row["price"])
        min_price = float(interval_df["price"].min())
        max_recovery_price = float(max_row["price"])
        future_min_price = float(min_row["price"])
        trade_count = int(len(interval_df))
        away_team = manifest["outcomes"][0]
        home_team = manifest["outcomes"][1]
        score_diff = int(start_row["away_score"]) - int(start_row["home_score"])
        if score_diff > 0:
            score_diff_display = f"{away_team} +{score_diff}"
        elif score_diff < 0:
            score_diff_display = f"{home_team} +{abs(score_diff)}"
        else:
            score_diff_display = "Tied"

        rows.append(
            {
                "team": team,
                "threshold": float(threshold),
                "entry_time": start_row["datetime"],
                "exit_time": exit_time,
                "duration_seconds": float(
                    (last_row["datetime"] - start_row["datetime"]).total_seconds()
                ),
                "period": int(start_row["period"]),
                "seconds_since_tipoff": int(start_row["seconds_since_tipoff"]),
                "time_bin": int(start_row["time_bin"]),
                "score_at_entry": f"{int(start_row['away_score'])}-{int(start_row['home_score'])}",
                "score_difference": score_diff_display,
                "entry_price": entry_price,
                "min_price": min_price,
                "max_recovery_price": max_recovery_price,
                "future_max_price": max_recovery_price,
                "future_min_price": future_min_price,
                "peak_rebound": float(max_recovery_price - entry_price),
                "time_to_peak_rebound_seconds": float(
                    (max_row["datetime"] - start_row["datetime"]).total_seconds()
                ),
                "further_drawdown": float(max(entry_price - future_min_price, 0.0)),
                "recovery_magnitude": float(max_recovery_price - min_price),
                "recovery_pct": float((max_recovery_price - min_price) / threshold)
                if threshold
                else 0.0,
                "time_to_max_recovery_seconds": float(
                    (max_row["datetime"] - start_row["datetime"]).total_seconds()
                ),
                "trade_count": trade_count,
                "low_confidence": bool(
                    trade_count < min_trades
                    or ((gaps > max_gap_seconds).any() if not gaps.empty else False)
                ),
                "resolution": resolution,
                "schema_version": DIP_RECOVERY_CACHE_SCHEMA_VERSION,
            }
        )

    return rows


def _serialize_rows(df: pd.DataFrame) -> list[dict]:
    records = df.to_dict("records")
    for record in records:
        record["entry_time"] = pd.Timestamp(record["entry_time"]).isoformat()
        record["exit_time"] = pd.Timestamp(record["exit_time"]).isoformat()
    return records


def _cache_has_required_columns(df: pd.DataFrame) -> bool:
    required = {
        "team",
        "threshold",
        "entry_time",
        "exit_time",
        "duration_seconds",
        "period",
        "seconds_since_tipoff",
        "time_bin",
        "score_at_entry",
        "score_difference",
        "entry_price",
        "min_price",
        "max_recovery_price",
        "future_max_price",
        "future_min_price",
        "peak_rebound",
        "time_to_peak_rebound_seconds",
        "further_drawdown",
        "recovery_magnitude",
        "recovery_pct",
        "time_to_max_recovery_seconds",
        "trade_count",
        "low_confidence",
        "resolution",
        "schema_version",
    }
    if not required.issubset(df.columns):
        return False
    return (
        df["schema_version"].nunique() == 1
        and int(df["schema_version"].iloc[0]) == DIP_RECOVERY_CACHE_SCHEMA_VERSION
    )
