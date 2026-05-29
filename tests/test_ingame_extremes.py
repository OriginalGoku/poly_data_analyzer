"""Tests for the per-team in-game extremes sidecar."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingame_extremes import (
    INGAME_EXTREMES_SCHEMA_VERSION,
    compute_ingame_extremes,
    compute_input_fingerprint,
    load_or_compute_ingame_extremes,
)


AWAY_TOKEN = "T_AWAY"
HOME_TOKEN = "T_HOME"
AWAY_TEAM = "Away"
HOME_TEAM = "Home"


def _ts(seconds_from_epoch: int):
    return pd.Timestamp(seconds_from_epoch, unit="s", tz="UTC")


def _manifest() -> dict:
    return {
        "match_id": "m1",
        "outcomes": [AWAY_TEAM, HOME_TEAM],
        "token_ids": [AWAY_TOKEN, HOME_TOKEN],
    }


def _trades_df(rows: list[tuple[int, str, float]]) -> pd.DataFrame:
    """rows: list of (epoch_seconds, asset_token, price)."""
    df = pd.DataFrame(
        [{"timestamp": ts, "asset": a, "price": p, "size": 1.0} for ts, a, p in rows]
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    return df


def _score_event(ts_epoch: int, away: int = 0, home: int = 0) -> dict:
    return {
        "time_actual_dt": _ts(ts_epoch),
        "away_score": away,
        "home_score": home,
    }


# --------------------------------------------------------------------------- #
# compute_ingame_extremes — window resolution branches
# --------------------------------------------------------------------------- #

def test_score_events_window_high_quality():
    events = [_score_event(100, 0, 0), _score_event(200, 1, 0), _score_event(300, 2, 1)]
    trades = _trades_df(
        [
            (50, AWAY_TOKEN, 0.4),  # pregame — excluded
            (150, AWAY_TOKEN, 0.6),  # in window
            (250, HOME_TOKEN, 0.7),  # in window: away_price = 0.3
            (400, AWAY_TOKEN, 0.9),  # post-window — excluded
        ]
    )
    row = compute_ingame_extremes(_manifest(), events, trades, _ts(50), _ts(500))
    assert row["tipoff_source"] == "score_events"
    assert row["window_quality"] == "high"
    assert row["away_in_game_min_price"] == pytest.approx(0.3)
    assert row["away_in_game_max_price"] == pytest.approx(0.6)
    assert row["home_in_game_min_price"] == pytest.approx(0.4)
    assert row["home_in_game_max_price"] == pytest.approx(0.7)


def test_gamma_closed_caps_window():
    events = [_score_event(100, 0, 0), _score_event(500, 2, 1)]
    trades = _trades_df(
        [
            (150, AWAY_TOKEN, 0.55),
            (250, AWAY_TOKEN, 0.95),  # would be max if gamma_closed didn't cap
            (450, AWAY_TOKEN, 0.7),
        ]
    )
    # gamma_closed=300 caps end before the 450 trade and before max score event at 500.
    row = compute_ingame_extremes(_manifest(), events, trades, _ts(50), _ts(300))
    assert row["away_in_game_max_price"] == pytest.approx(0.95)
    # 450 trade was outside the cap; verify min picks among in-window trades only.
    assert row["away_in_game_min_price"] == pytest.approx(0.55)


def test_gamma_fallback_medium_quality():
    trades = _trades_df(
        [
            (50, AWAY_TOKEN, 0.4),  # pregame
            (150, AWAY_TOKEN, 0.6),
            (250, AWAY_TOKEN, 0.8),
            (350, AWAY_TOKEN, 0.95),  # outside gamma_closed
        ]
    )
    row = compute_ingame_extremes(_manifest(), events=None, trades_df=trades, gamma_start=_ts(100), gamma_closed=_ts(300))
    assert row["tipoff_source"] == "gamma_fallback"
    assert row["window_quality"] == "medium"
    assert row["away_in_game_min_price"] == pytest.approx(0.6)
    assert row["away_in_game_max_price"] == pytest.approx(0.8)


def test_gamma_fallback_uncapped_low_quality():
    trades = _trades_df(
        [
            (50, AWAY_TOKEN, 0.4),  # pre
            (150, AWAY_TOKEN, 0.6),
            (350, AWAY_TOKEN, 0.9),
        ]
    )
    row = compute_ingame_extremes(_manifest(), events=None, trades_df=trades, gamma_start=_ts(100), gamma_closed=None)
    assert row["tipoff_source"] == "gamma_fallback_uncapped"
    assert row["window_quality"] == "low"
    assert row["away_in_game_min_price"] == pytest.approx(0.6)
    assert row["away_in_game_max_price"] == pytest.approx(0.9)


def test_unavailable_when_no_signals():
    trades = _trades_df([(100, AWAY_TOKEN, 0.5)])
    row = compute_ingame_extremes(_manifest(), events=None, trades_df=trades, gamma_start=None, gamma_closed=None)
    assert row["tipoff_source"] == "unavailable"
    assert row["window_quality"] == "none"
    assert row["away_in_game_min_price"] is None
    assert row["home_in_game_max_price"] is None


def test_per_team_with_home_token_major_order():
    """Home-token trades come first; per-team flip still produces correct away/home extremes."""
    events = [_score_event(100), _score_event(200)]
    trades = _trades_df(
        [
            (110, HOME_TOKEN, 0.8),  # away_price = 0.2
            (120, HOME_TOKEN, 0.3),  # away_price = 0.7
            (130, AWAY_TOKEN, 0.5),  # away_price = 0.5
        ]
    )
    row = compute_ingame_extremes(_manifest(), events, trades, _ts(0), _ts(300))
    assert row["away_in_game_min_price"] == pytest.approx(0.2)
    assert row["away_in_game_max_price"] == pytest.approx(0.7)
    assert row["home_in_game_min_price"] == pytest.approx(0.3)
    assert row["home_in_game_max_price"] == pytest.approx(0.8)


def test_empty_trades_returns_empty_row():
    row = compute_ingame_extremes(_manifest(), events=None, trades_df=pd.DataFrame(), gamma_start=_ts(100), gamma_closed=_ts(300))
    assert row["away_in_game_min_price"] is None
    assert row["tipoff_source"] == "unavailable"


# --------------------------------------------------------------------------- #
# load_or_compute_ingame_extremes — caching behavior
# --------------------------------------------------------------------------- #

def _write_input_files(data_dir: Path, date: str, match_id: str) -> None:
    base = data_dir / date
    base.mkdir(parents=True, exist_ok=True)
    (base / "manifest.json").write_text(json.dumps([{"match_id": match_id}]))
    (base / f"{match_id}_trades.json.gz").write_bytes(b"\x1f\x8b\x08\x00\x00\x00\x00\x00")
    (base / f"{match_id}_events.json.gz").write_bytes(b"\x1f\x8b\x08\x00\x00\x00\x00\x00")


def _game_fixture() -> dict:
    events = [_score_event(100, 0, 0), _score_event(200, 1, 0)]
    trades = _trades_df([(150, AWAY_TOKEN, 0.6)])
    return {
        "manifest": _manifest(),
        "trades_df": trades,
        "events": events,
        "gamma_start": _ts(50),
        "gamma_closed": _ts(500),
    }


class _ProviderCounter:
    def __init__(self, game):
        self.calls = 0
        self.game = game

    def __call__(self):
        self.calls += 1
        return self.game


def test_cache_miss_writes_sidecar(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _write_input_files(data_dir, "2026-04-10", "m1")
    provider = _ProviderCounter(_game_fixture())

    row = load_or_compute_ingame_extremes(
        cache_dir, data_dir, "2026-04-10", "m1", game_provider=provider
    )
    assert row["away_in_game_max_price"] == pytest.approx(0.6)
    sidecar = cache_dir / "2026-04-10" / "m1_ingame_extremes.json"
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text())
    assert payload["schema_version"] == INGAME_EXTREMES_SCHEMA_VERSION
    assert payload["input_fingerprint"] == compute_input_fingerprint(data_dir, "2026-04-10", "m1")
    assert "settings_hash" not in payload
    assert provider.calls == 1


def test_cache_hit_skips_provider(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _write_input_files(data_dir, "2026-04-10", "m1")
    provider = _ProviderCounter(_game_fixture())

    load_or_compute_ingame_extremes(cache_dir, data_dir, "2026-04-10", "m1", game_provider=provider)
    load_or_compute_ingame_extremes(cache_dir, data_dir, "2026-04-10", "m1", game_provider=provider)
    assert provider.calls == 1


def test_fingerprint_mismatch_triggers_recompute(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _write_input_files(data_dir, "2026-04-10", "m1")
    provider = _ProviderCounter(_game_fixture())

    load_or_compute_ingame_extremes(cache_dir, data_dir, "2026-04-10", "m1", game_provider=provider)
    trades_path = data_dir / "2026-04-10" / "m1_trades.json.gz"
    future = time.time() + 60
    os.utime(trades_path, (future, future))

    load_or_compute_ingame_extremes(cache_dir, data_dir, "2026-04-10", "m1", game_provider=provider)
    assert provider.calls == 2


def test_schema_mismatch_triggers_recompute(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _write_input_files(data_dir, "2026-04-10", "m1")
    sidecar = cache_dir / "2026-04-10" / "m1_ingame_extremes.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({"schema_version": 999, "input_fingerprint": "stale", "row": {"old": True}}))
    provider = _ProviderCounter(_game_fixture())

    row = load_or_compute_ingame_extremes(cache_dir, data_dir, "2026-04-10", "m1", game_provider=provider)
    assert "away_in_game_max_price" in row
    assert provider.calls == 1
