"""Regime transition detection and caching."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from analytics import INTERPRETABLE_BAND_LABELS, _assign_interpretable_band


REGIME_TRANSITIONS_CACHE_SCHEMA_VERSION = 1
BAND_RANK = {label: index for index, label in enumerate(INTERPRETABLE_BAND_LABELS)}


def compute_regime_transitions(
    trades_df: pd.DataFrame,
    events: list[dict] | None,
    manifest: dict,
    settings,
) -> pd.DataFrame | None:
    """Detect confirmed favorite-side band transitions during in-game trading."""
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
    away_token = manifest["token_ids"][0]
    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]
    min_confirm = max(int(getattr(settings, "regime_min_trades_in_window", 3)), 1)
    max_gap_seconds = int(getattr(settings, "regime_max_trade_gap_seconds", 120))
    horizon_minutes = int(getattr(settings, "regime_forward_horizon_minutes", 12))

    away_trades = trades_df[
        (trades_df["asset"] == away_token)
        & (trades_df["datetime"] >= tipoff_time)
        & (trades_df["datetime"] <= game_end)
    ].sort_values("datetime").copy()
    if away_trades.empty:
        return None

    score_df = pd.DataFrame(
        {
            "datetime": [event["time_actual_dt"] for event in score_events],
            "period": [int(event.get("period") or 0) for event in score_events],
        }
    ).sort_values("datetime")
    aligned = pd.merge_asof(away_trades, score_df, on="datetime", direction="backward")
    aligned = aligned.dropna(subset=["period"]).reset_index(drop=True)
    if aligned.empty:
        return None

    aligned["away_price"] = aligned["price"].astype(float)
    aligned["home_price"] = 1.0 - aligned["away_price"]
    aligned["favorite_side_price"] = aligned[["away_price", "home_price"]].max(axis=1)
    aligned["favorite_team"] = aligned["away_price"].apply(
        lambda price: away_team if price >= 0.5 else home_team
    )
    aligned["band"] = aligned["favorite_side_price"].apply(_assign_interpretable_band)
    aligned["seconds_since_tipoff"] = (
        aligned["datetime"] - tipoff_time
    ).dt.total_seconds().astype(int)
    aligned["time_bin"] = aligned["seconds_since_tipoff"] // 360

    runs = []
    run_start = 0
    for index in range(1, len(aligned) + 1):
        if index == len(aligned) or aligned.iloc[index]["band"] != aligned.iloc[run_start]["band"]:
            run = aligned.iloc[run_start:index].copy()
            runs.append(run)
            run_start = index

    rows: list[dict] = []
    for prior_run, current_run in zip(runs, runs[1:]):
        from_band = prior_run.iloc[0]["band"]
        to_band = current_run.iloc[0]["band"]
        if from_band is None or to_band is None or from_band == to_band:
            continue
        if len(current_run) < min_confirm:
            continue

        transition_row = current_run.iloc[0]
        forward_window = aligned[
            (aligned["datetime"] >= transition_row["datetime"])
            & (
                aligned["datetime"]
                <= transition_row["datetime"] + pd.Timedelta(minutes=horizon_minutes)
            )
        ].copy()
        if forward_window.empty:
            continue

        max_row = forward_window.loc[forward_window["favorite_side_price"].idxmax()]
        min_row = forward_window.loc[forward_window["favorite_side_price"].idxmin()]
        gaps = forward_window["datetime"].diff().dt.total_seconds().dropna()
        low_confidence = bool(
            len(forward_window) < min_confirm
            or ((gaps > max_gap_seconds).any() if not gaps.empty else False)
        )

        rows.append(
            {
                "transition_time": transition_row["datetime"],
                "from_band": from_band,
                "to_band": to_band,
                "transition_label": f"{from_band} → {to_band}",
                "transition_direction": _transition_direction(from_band, to_band),
                "favorite_team": transition_row["favorite_team"],
                "price_at_transition": float(transition_row["favorite_side_price"]),
                "period": int(transition_row["period"]),
                "seconds_since_tipoff": int(transition_row["seconds_since_tipoff"]),
                "time_bin": int(transition_row["time_bin"]),
                "forward_max_price": float(max_row["favorite_side_price"]),
                "forward_min_price": float(min_row["favorite_side_price"]),
                "forward_return_max": float(
                    max_row["favorite_side_price"] - transition_row["favorite_side_price"]
                ),
                "forward_time_to_max_seconds": float(
                    (max_row["datetime"] - transition_row["datetime"]).total_seconds()
                ),
                "trades_in_window": int(len(forward_window)),
                "low_confidence": low_confidence,
                "schema_version": REGIME_TRANSITIONS_CACHE_SCHEMA_VERSION,
            }
        )

    if not rows:
        return None
    return pd.DataFrame(rows)


def load_or_compute_regime_transitions(
    cache_dir: str | Path,
    date: str,
    match_id: str,
    trades_df: pd.DataFrame,
    events: list[dict] | None,
    manifest: dict,
    settings,
) -> pd.DataFrame | None:
    """Load cached regime transitions or compute and cache them."""
    cache_path = Path(cache_dir) / date / f"{match_id}_regime_transitions.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text())
        if not payload:
            return None
        df = pd.DataFrame(payload)
        if _cache_has_required_columns(df):
            df["transition_time"] = pd.to_datetime(df["transition_time"], utc=True, format="mixed")
            return df

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    transition_df = compute_regime_transitions(trades_df, events, manifest, settings)
    serialized = [] if transition_df is None else _serialize_rows(transition_df)
    cache_path.write_text(json.dumps(serialized, indent=2) + "\n")
    return transition_df


def _transition_direction(from_band: str, to_band: str) -> str:
    return "upgrade" if BAND_RANK[to_band] > BAND_RANK[from_band] else "downgrade"


def _serialize_rows(df: pd.DataFrame) -> list[dict]:
    records = df.to_dict("records")
    for record in records:
        record["transition_time"] = pd.Timestamp(record["transition_time"]).isoformat()
    return records


def _cache_has_required_columns(df: pd.DataFrame) -> bool:
    required = {
        "transition_time",
        "from_band",
        "to_band",
        "transition_label",
        "transition_direction",
        "favorite_team",
        "price_at_transition",
        "period",
        "seconds_since_tipoff",
        "time_bin",
        "forward_max_price",
        "forward_min_price",
        "forward_return_max",
        "forward_time_to_max_seconds",
        "trades_in_window",
        "low_confidence",
        "schema_version",
    }
    if not required.issubset(df.columns):
        return False
    return (
        df["schema_version"].nunique() == 1
        and int(df["schema_version"].iloc[0]) == REGIME_TRANSITIONS_CACHE_SCHEMA_VERSION
    )
