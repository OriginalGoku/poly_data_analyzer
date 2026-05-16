"""Tests for the persistent NBA tipoff detail cache."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nba_tipoff_cache import (
    NBA_TIPOFF_CACHE_SCHEMA_VERSION,
    load_or_compute_nba_tipoff_detail,
)
from settings import ChartSettings


def _write_minimal_game_files(data_dir: Path, date: str, match_id: str) -> dict:
    """Write minimal manifest/trades/events files so input_fingerprint can stat them."""
    base = data_dir / date
    base.mkdir(parents=True, exist_ok=True)
    manifest = [{"match_id": match_id, "status": "collected"}]
    (base / "manifest.json").write_text(json.dumps(manifest))
    (base / f"{match_id}_trades.json.gz").write_bytes(b"\x1f\x8b\x08\x00\x00\x00\x00\x00")
    (base / f"{match_id}_events.json.gz").write_bytes(b"\x1f\x8b\x08\x00\x00\x00\x00\x00")
    return {"manifest": manifest[0]}


class _ComputeCounter:
    def __init__(self, row):
        self.calls = 0
        self.row = row

    def __call__(self, game, settings, team, price):
        self.calls += 1
        return dict(self.row)


def test_cache_miss_writes_and_returns_row(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _write_minimal_game_files(data_dir, "2026-04-10", "nba-1")
    compute = _ComputeCounter({"open_favorite_in_game_min_price": 0.5})
    settings = ChartSettings(pregame_min_cum_vol=5000)

    row = load_or_compute_nba_tipoff_detail(
        cache_dir=cache_dir,
        data_dir=data_dir,
        date="2026-04-10",
        match_id="nba-1",
        game={"trades_df": None, "events": None, "manifest": {}},
        settings=settings,
        open_favorite_team="A",
        open_favorite_price=0.6,
        compute_fn=compute,
    )

    assert row == {"open_favorite_in_game_min_price": 0.5}
    assert compute.calls == 1
    cache_path = cache_dir / "2026-04-10" / "nba-1_nba_tipoff.json"
    assert cache_path.exists()
    payload = json.loads(cache_path.read_text())
    assert payload["schema_version"] == NBA_TIPOFF_CACHE_SCHEMA_VERSION
    assert payload["row"] == row


def test_cache_hit_skips_compute(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _write_minimal_game_files(data_dir, "2026-04-10", "nba-1")
    settings = ChartSettings(pregame_min_cum_vol=5000)
    compute = _ComputeCounter({"open_favorite_in_game_max_price": 0.9})

    args = dict(
        cache_dir=cache_dir,
        data_dir=data_dir,
        date="2026-04-10",
        match_id="nba-1",
        game={"trades_df": None, "events": None, "manifest": {}},
        settings=settings,
        open_favorite_team="A",
        open_favorite_price=0.6,
        compute_fn=compute,
    )

    load_or_compute_nba_tipoff_detail(**args)
    assert compute.calls == 1
    load_or_compute_nba_tipoff_detail(**args)
    assert compute.calls == 1  # second call must be a cache hit


def test_settings_hash_invalidates_on_change(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _write_minimal_game_files(data_dir, "2026-04-10", "nba-1")
    compute = _ComputeCounter({"any_favorite_switch_pregame": False})

    load_or_compute_nba_tipoff_detail(
        cache_dir=cache_dir,
        data_dir=data_dir,
        date="2026-04-10",
        match_id="nba-1",
        game={"trades_df": None, "events": None, "manifest": {}},
        settings=ChartSettings(pregame_min_cum_vol=5000),
        open_favorite_team="A",
        open_favorite_price=0.6,
        compute_fn=compute,
    )
    assert compute.calls == 1

    load_or_compute_nba_tipoff_detail(
        cache_dir=cache_dir,
        data_dir=data_dir,
        date="2026-04-10",
        match_id="nba-1",
        game={"trades_df": None, "events": None, "manifest": {}},
        settings=ChartSettings(pregame_min_cum_vol=9999),  # changed
        open_favorite_team="A",
        open_favorite_price=0.6,
        compute_fn=compute,
    )
    assert compute.calls == 2


def test_schema_version_mismatch_invalidates(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _write_minimal_game_files(data_dir, "2026-04-10", "nba-1")
    cache_path = cache_dir / "2026-04-10" / "nba-1_nba_tipoff.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 999,
                "settings_hash": "x",
                "input_fingerprint": "y",
                "row": {"old": True},
            }
        )
    )
    compute = _ComputeCounter({"new": True})

    row = load_or_compute_nba_tipoff_detail(
        cache_dir=cache_dir,
        data_dir=data_dir,
        date="2026-04-10",
        match_id="nba-1",
        game={"trades_df": None, "events": None, "manifest": {}},
        settings=ChartSettings(pregame_min_cum_vol=5000),
        open_favorite_team="A",
        open_favorite_price=0.6,
        compute_fn=compute,
    )
    assert row == {"new": True}
    assert compute.calls == 1


def test_input_fingerprint_invalidates_on_trades_mtime_change(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _write_minimal_game_files(data_dir, "2026-04-10", "nba-1")
    settings = ChartSettings(pregame_min_cum_vol=5000)
    compute = _ComputeCounter({"row": 1})

    args = dict(
        cache_dir=cache_dir,
        data_dir=data_dir,
        date="2026-04-10",
        match_id="nba-1",
        game={"trades_df": None, "events": None, "manifest": {}},
        settings=settings,
        open_favorite_team="A",
        open_favorite_price=0.6,
        compute_fn=compute,
    )
    load_or_compute_nba_tipoff_detail(**args)
    assert compute.calls == 1

    trades_path = data_dir / "2026-04-10" / "nba-1_trades.json.gz"
    future = time.time() + 60
    os.utime(trades_path, (future, future))

    load_or_compute_nba_tipoff_detail(**args)
    assert compute.calls == 2


def test_input_fingerprint_invalidates_on_events_mtime_change(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _write_minimal_game_files(data_dir, "2026-04-10", "nba-1")
    settings = ChartSettings(pregame_min_cum_vol=5000)
    compute = _ComputeCounter({"row": 1})

    args = dict(
        cache_dir=cache_dir,
        data_dir=data_dir,
        date="2026-04-10",
        match_id="nba-1",
        game={"trades_df": None, "events": None, "manifest": {}},
        settings=settings,
        open_favorite_team="A",
        open_favorite_price=0.6,
        compute_fn=compute,
    )
    load_or_compute_nba_tipoff_detail(**args)
    assert compute.calls == 1

    events_path = data_dir / "2026-04-10" / "nba-1_events.json.gz"
    future = time.time() + 60
    os.utime(events_path, (future, future))

    load_or_compute_nba_tipoff_detail(**args)
    assert compute.calls == 2


def test_game_provider_skipped_on_cache_hit(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _write_minimal_game_files(data_dir, "2026-04-10", "nba-1")
    settings = ChartSettings(pregame_min_cum_vol=5000)
    compute = _ComputeCounter({"row": 1})

    # First call (miss) — provider may be called.
    provider_calls = {"n": 0}
    def provider():
        provider_calls["n"] += 1
        return {"trades_df": None, "events": None, "manifest": {}}

    args = dict(
        cache_dir=cache_dir,
        data_dir=data_dir,
        date="2026-04-10",
        match_id="nba-1",
        settings=settings,
        open_favorite_team="A",
        open_favorite_price=0.6,
        compute_fn=compute,
        game_provider=provider,
    )
    load_or_compute_nba_tipoff_detail(**args)
    assert provider_calls["n"] == 1
    assert compute.calls == 1

    # Second call (hit) — provider must NOT be touched.
    load_or_compute_nba_tipoff_detail(**args)
    assert provider_calls["n"] == 1
    assert compute.calls == 1
