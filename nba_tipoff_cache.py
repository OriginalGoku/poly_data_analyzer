"""Persistent per-game disk cache for NBA tipoff detail rows."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable


NBA_TIPOFF_CACHE_SCHEMA_VERSION = 1


def _stable_hash(parts: tuple) -> str:
    """Deterministic SHA1 over a tuple of primitive values."""
    payload = json.dumps(parts, default=str, sort_keys=True).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()


def compute_settings_hash(settings, open_favorite_team, open_favorite_price) -> str:
    return _stable_hash(
        (
            float(getattr(settings, "pregame_min_cum_vol", 0)),
            float(getattr(settings, "vol_spike_std", 0)),
            int(getattr(settings, "vol_spike_lookback", 0)),
            float(getattr(settings, "post_game_buffer_min", 0)),
            open_favorite_team,
            None if open_favorite_price is None else float(open_favorite_price),
        )
    )


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


def load_or_compute_nba_tipoff_detail(
    cache_dir: str | Path,
    data_dir: str | Path,
    date: str,
    match_id: str,
    settings,
    open_favorite_team: str | None,
    open_favorite_price: float | None,
    compute_fn: Callable[[dict, Any, str | None, float | None], dict],
    game_provider: Callable[[], dict] | None = None,
    game: dict | None = None,
) -> dict:
    """Return cached detail-row dict for (date, match_id) or compute and persist it.

    Either `game` (eager) or `game_provider` (lazy callable) must be supplied;
    on a cache hit neither is touched, so a `game_provider` is preferred when
    loading the game would require expensive I/O.
    """
    cache_path = Path(cache_dir) / date / f"{match_id}_nba_tipoff.json"
    settings_hash = compute_settings_hash(settings, open_favorite_team, open_favorite_price)
    input_fingerprint = compute_input_fingerprint(data_dir, date, match_id)

    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            payload = None
        if (
            isinstance(payload, dict)
            and payload.get("schema_version") == NBA_TIPOFF_CACHE_SCHEMA_VERSION
            and payload.get("settings_hash") == settings_hash
            and payload.get("input_fingerprint") == input_fingerprint
            and isinstance(payload.get("row"), dict)
        ):
            return payload["row"]

    if game is None:
        if game_provider is None:
            raise ValueError("load_or_compute_nba_tipoff_detail: provide game or game_provider")
        game = game_provider()
    row = compute_fn(game, settings, open_favorite_team, open_favorite_price)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": NBA_TIPOFF_CACHE_SCHEMA_VERSION,
                "settings_hash": settings_hash,
                "input_fingerprint": input_fingerprint,
                "row": row,
            },
            default=str,
            indent=2,
        )
        + "\n"
    )
    return row
