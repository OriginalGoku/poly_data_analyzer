"""Per-team in-game price extremes sidecar (settings-independent).

Persists at ``cache/<date>/<match_id>_ingame_extremes.json`` with payload:

    {
      "schema_version": INGAME_EXTREMES_SCHEMA_VERSION,
      "input_fingerprint": <sha1>,
      "row": {
          "away_team": str | None,
          "home_team": str | None,
          "away_in_game_min_price": float | None,
          "away_in_game_max_price": float | None,
          "home_in_game_min_price": float | None,
          "home_in_game_max_price": float | None,
          "tipoff_source": "score_events" | "gamma_fallback" | "gamma_fallback_uncapped" | "unavailable",
          "window_quality": "high" | "medium" | "low" | "none",
          "window_start": ISO-8601 str | None,
          "window_end": ISO-8601 str | None,
      },
    }

Settings-independent: no ``settings_hash`` field — extremes survive future
settings-hash changes without recompute. Cache only invalidates on
``schema_version`` mismatch or ``input_fingerprint`` mismatch.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

import pandas as pd


INGAME_EXTREMES_SCHEMA_VERSION = 2


def _stable_hash(parts: tuple) -> str:
    payload = json.dumps(parts, default=str, sort_keys=True).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()


def _file_fingerprint(path: Path) -> tuple[int | None, int | None]:
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return (None, None)


def compute_input_fingerprint(data_dir: str | Path, date: str, match_id: str) -> str:
    base = Path(data_dir) / date
    trades_fp = _file_fingerprint(base / f"{match_id}_trades.json.gz")
    manifest_fp = _file_fingerprint(base / "manifest.json")
    events_fp = _file_fingerprint(base / f"{match_id}_events.json.gz")
    return _stable_hash((trades_fp, manifest_fp, events_fp))


def _empty_row(away_team: str | None, home_team: str | None) -> dict:
    return {
        "away_team": away_team,
        "home_team": home_team,
        "away_in_game_min_price": None,
        "away_in_game_max_price": None,
        "home_in_game_min_price": None,
        "home_in_game_max_price": None,
        "away_full_min_price": None,
        "away_full_max_price": None,
        "home_full_min_price": None,
        "home_full_max_price": None,
        "tipoff_source": "unavailable",
        "window_quality": "none",
        "window_start": None,
        "window_end": None,
    }


def _per_team_prices(trades_df, away_token: str):
    """Return (away_price, home_price) Series aligned to trades_df.index."""
    away_price = trades_df["price"].astype(float).copy()
    home_mask = (trades_df["asset"] != away_token).values
    away_price.loc[trades_df.index[home_mask]] = 1.0 - away_price.loc[trades_df.index[home_mask]]
    return away_price, 1.0 - away_price


def _has_score_events(events: list[dict] | None) -> bool:
    if not events:
        return False
    for ev in events:
        if (
            ev.get("time_actual_dt") is not None
            and ev.get("away_score") is not None
            and ev.get("home_score") is not None
        ):
            return True
    return False


def _resolve_window(
    events: list[dict] | None,
    gamma_start,
    gamma_closed,
    last_trade_ts,
) -> tuple[Any, Any, str, str]:
    """Return (window_start, window_end, tipoff_source, window_quality)."""
    if _has_score_events(events):
        score_times = [
            ev["time_actual_dt"]
            for ev in events
            if ev.get("time_actual_dt") is not None
            and ev.get("away_score") is not None
            and ev.get("home_score") is not None
        ]
        tipoff = min(score_times)
        end_candidates = [max(score_times)]
        if gamma_closed is not None:
            end_candidates.append(gamma_closed)
        if last_trade_ts is not None:
            end_candidates.append(last_trade_ts)
        return tipoff, min(end_candidates), "score_events", "high"

    if gamma_start is not None and gamma_closed is not None:
        end_candidates = [gamma_closed]
        if last_trade_ts is not None:
            end_candidates.append(last_trade_ts)
        return gamma_start, min(end_candidates), "gamma_fallback", "medium"

    if gamma_start is not None and last_trade_ts is not None:
        return gamma_start, last_trade_ts, "gamma_fallback_uncapped", "low"

    return None, None, "unavailable", "none"


def compute_ingame_extremes(
    manifest: dict,
    events: list[dict] | None,
    trades_df: pd.DataFrame,
    gamma_start,
    gamma_closed,
) -> dict:
    """Compute per-team in-game min/max prices. Pure function — no I/O.

    Returns the sidecar ``row`` payload (caller adds schema/fingerprint wrappers).
    Caller may pass already-loaded ``events`` and ``trades_df`` to skip disk
    reads.
    """
    outcomes = manifest.get("outcomes") or []
    token_ids = manifest.get("token_ids") or []
    away_team = outcomes[0] if len(outcomes) >= 1 else None
    home_team = outcomes[1] if len(outcomes) >= 2 else None

    if trades_df is None or trades_df.empty or len(token_ids) < 2 or len(outcomes) < 2:
        return _empty_row(away_team, home_team)

    last_trade_ts = trades_df["datetime"].max() if "datetime" in trades_df.columns else None
    window_start, window_end, tipoff_source, window_quality = _resolve_window(
        events, gamma_start, gamma_closed, last_trade_ts
    )

    row = _empty_row(away_team, home_team)
    row["tipoff_source"] = tipoff_source
    row["window_quality"] = window_quality

    away_token = token_ids[0]
    away_full, home_full = _per_team_prices(trades_df, away_token)
    away_full_clean = away_full.dropna()
    home_full_clean = home_full.dropna()
    if not away_full_clean.empty:
        row["away_full_min_price"] = float(away_full_clean.min())
        row["away_full_max_price"] = float(away_full_clean.max())
    if not home_full_clean.empty:
        row["home_full_min_price"] = float(home_full_clean.min())
        row["home_full_max_price"] = float(home_full_clean.max())

    if window_start is None or window_end is None or window_end <= window_start:
        return row

    ingame = trades_df[
        (trades_df["datetime"] >= window_start) & (trades_df["datetime"] <= window_end)
    ].sort_values("datetime")
    row["window_start"] = window_start.isoformat() if hasattr(window_start, "isoformat") else str(window_start)
    row["window_end"] = window_end.isoformat() if hasattr(window_end, "isoformat") else str(window_end)
    if ingame.empty:
        return row

    away_price, home_price = _per_team_prices(ingame, away_token)
    away_clean = away_price.dropna()
    home_clean = home_price.dropna()
    if not away_clean.empty:
        row["away_in_game_min_price"] = float(away_clean.min())
        row["away_in_game_max_price"] = float(away_clean.max())
    if not home_clean.empty:
        row["home_in_game_min_price"] = float(home_clean.min())
        row["home_in_game_max_price"] = float(home_clean.max())

    return row


def _write_payload_atomic(cache_path: Path, payload: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, default=str, indent=2) + "\n")
    os.replace(tmp, cache_path)


def load_or_compute_ingame_extremes(
    cache_dir: str | Path,
    data_dir: str | Path,
    date: str,
    match_id: str,
    game_provider: Callable[[], dict] | None = None,
    game: dict | None = None,
) -> dict:
    """Return cached extremes row for (date, match_id), or compute and persist.

    Either ``game`` (eager) or ``game_provider`` (lazy callable) must be
    supplied; on a cache hit neither is touched.
    """
    cache_path = Path(cache_dir) / date / f"{match_id}_ingame_extremes.json"
    input_fingerprint = compute_input_fingerprint(data_dir, date, match_id)

    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            payload = None
        if (
            isinstance(payload, dict)
            and payload.get("schema_version") == INGAME_EXTREMES_SCHEMA_VERSION
            and payload.get("input_fingerprint") == input_fingerprint
            and isinstance(payload.get("row"), dict)
        ):
            return payload["row"]

    if game is None:
        if game_provider is None:
            raise ValueError(
                "load_or_compute_ingame_extremes: provide game or game_provider"
            )
        game = game_provider()

    row = compute_ingame_extremes(
        game["manifest"],
        game.get("events"),
        game["trades_df"],
        game.get("gamma_start"),
        game.get("gamma_closed"),
    )
    _write_payload_atomic(
        cache_path,
        {
            "schema_version": INGAME_EXTREMES_SCHEMA_VERSION,
            "input_fingerprint": input_fingerprint,
            "row": row,
        },
    )
    return row
