"""Per-event price sensitivity computation and caching."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


SCORING_POINTS = {
    "freethrow": 1,
    "2pt": 2,
    "3pt": 3,
}


def compute_event_sensitivity(
    trades_df: pd.DataFrame,
    events: list[dict] | None,
    manifest: dict,
    settings,
) -> pd.DataFrame | None:
    """Compute per-event price sensitivity for a single game's scoring plays."""
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

    tipoff_time = score_events[0]["time_actual_dt"]
    away_token = manifest["token_ids"][0]
    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]
    window = max(int(getattr(settings, "sensitivity_price_window_trades", 5)), 1)

    away_trades = trades_df[
        (trades_df["asset"] == away_token) & (trades_df["datetime"] >= tipoff_time)
    ].sort_values("datetime")
    if away_trades.empty:
        return None

    rows: list[dict] = []
    prev_away = 0
    prev_home = 0

    for ev in score_events:
        away_score = int(ev.get("away_score") or 0)
        home_score = int(ev.get("home_score") or 0)
        away_delta = away_score - prev_away
        home_delta = home_score - prev_home

        if away_delta <= 0 and home_delta <= 0:
            prev_away = away_score
            prev_home = home_score
            continue

        team = away_team if away_delta > home_delta else home_team
        points = SCORING_POINTS.get(ev.get("event_type"), max(away_delta, home_delta))
        pre_lead = abs(prev_away - prev_home)
        post_lead = abs(away_score - home_score)
        event_time = ev["time_actual_dt"]

        trades_before = away_trades[away_trades["datetime"] < event_time].tail(window)
        trades_after = away_trades[away_trades["datetime"] >= event_time].head(window)
        price_before = _compute_vwap(trades_before)
        price_after = _compute_vwap(trades_after)
        delta_price = (
            price_after - price_before
            if price_before is not None and price_after is not None
            else None
        )
        seconds_since_tipoff = int((event_time - tipoff_time).total_seconds())

        rows.append(
            {
                "event_time": event_time,
                "team": team,
                "points": points,
                "period": int(ev.get("period") or 0),
                "seconds_since_tipoff": seconds_since_tipoff,
                "pre_lead": pre_lead,
                "post_lead": post_lead,
                "lead_bin": _classify_lead_bin(pre_lead, settings),
                "time_bin": seconds_since_tipoff // 360,
                "price_before": price_before,
                "price_after": price_after,
                "delta_price": delta_price,
                "trades_before_count": int(len(trades_before)),
                "trades_after_count": int(len(trades_after)),
            }
        )

        prev_away = away_score
        prev_home = home_score

    if not rows:
        return None

    sensitivity_df = pd.DataFrame(rows)
    if sensitivity_df["delta_price"].notna().sum() == 0:
        return None
    return sensitivity_df


def load_or_compute_sensitivity(
    cache_dir: str | Path,
    date: str,
    match_id: str,
    trades_df: pd.DataFrame,
    events: list[dict] | None,
    manifest: dict,
    settings,
) -> pd.DataFrame | None:
    """Load cached sensitivity rows or compute and cache them."""
    cache_path = Path(cache_dir) / date / f"{match_id}_sensitivity.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text())
        if not payload:
            return None
        df = pd.DataFrame(payload)
        df["event_time"] = pd.to_datetime(df["event_time"], utc=True)
        return df

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    sensitivity_df = compute_event_sensitivity(trades_df, events, manifest, settings)
    serialized = [] if sensitivity_df is None else _serialize_rows(sensitivity_df)
    cache_path.write_text(json.dumps(serialized, indent=2) + "\n")
    return sensitivity_df


def _compute_vwap(trades: pd.DataFrame) -> float | None:
    """Compute VWAP for the provided trades slice."""
    if trades.empty:
        return None
    total_size = trades["size"].sum()
    if total_size <= 0:
        return None
    return float((trades["price"] * trades["size"]).sum() / total_size)


def _classify_lead_bin(pre_lead: int, settings) -> str:
    close_threshold = int(getattr(settings, "sensitivity_lead_bin_close", 5))
    moderate_threshold = int(getattr(settings, "sensitivity_lead_bin_moderate", 12))
    if pre_lead <= close_threshold:
        return "Close"
    if pre_lead <= moderate_threshold:
        return "Moderate"
    return "Blowout"


def _serialize_rows(df: pd.DataFrame) -> list[dict]:
    records = df.to_dict("records")
    for record in records:
        record["event_time"] = pd.Timestamp(record["event_time"]).isoformat()
    return records
