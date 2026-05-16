"""Tests for stream_game_analytics + base-records disk cache."""

from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analytics
from analytics import (
    _base_records_settings_hash,
    _load_base_records_cache,
    _save_base_records_cache,
    stream_game_analytics,
)


def _write_trade_file(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)


def _write_manifest(path: Path, entries: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f)


def _seed_game(data_root: Path, date: str, match_id: str, *, fav_price: float = 0.65):
    date_dir = data_root / date
    manifest_entry = {
        "match_id": match_id,
        "sport": "nba",
        "status": "collected",
        "away_team": "Away",
        "home_team": "Home",
        "outcomes": ["Away", "Home"],
        "token_ids": [f"{match_id}-a", f"{match_id}-h"],
    }
    manifest_path = date_dir / "manifest.json"
    existing: list[dict] = []
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        existing = [e for e in existing if e.get("match_id") != match_id]
    existing.append(manifest_entry)
    _write_manifest(manifest_path, existing)
    _write_trade_file(
        date_dir / f"{match_id}_trades.json.gz",
        {
            "match_id": match_id,
            "sport": "nba",
            "price_checkpoints_meta": {"price_quality": "exact"},
            "price_checkpoints": {
                f"{match_id}-a": {
                    "selected_early_price": 1 - fav_price,
                    "selected_early_price_source": "clob_open",
                    "last_pregame_trade_price": 1 - fav_price,
                },
                f"{match_id}-h": {
                    "selected_early_price": fav_price,
                    "selected_early_price_source": "clob_open",
                    "last_pregame_trade_price": fav_price,
                },
            },
            "trades": [
                {"timestamp": 1, "asset": f"{match_id}-a", "price": 1 - fav_price, "size": 3000},
                {"timestamp": 2, "asset": f"{match_id}-h", "price": fav_price, "size": 3000},
            ],
        },
    )
    return manifest_entry


class TestStreamGameAnalyticsBasic:
    def test_yields_record_and_lazy_get_game(self, tmp_path):
        data = tmp_path / "data"
        _seed_game(data, "2026-04-10", "g1")

        results = list(stream_game_analytics(str(data), pregame_min_cum_vol=5000))

        assert len(results) == 1
        record, get_game = results[0]
        assert record["match_id"] == "g1"
        assert record["open_favorite_team"] == "Home"
        assert record["open_interpretable_band"] is not None  # band assigned

        # get_game is callable and memoized
        game1 = get_game()
        game2 = get_game()
        assert game1 is game2
        assert game1["manifest"]["match_id"] == "g1"
        assert "trades_df" in game1

    def test_respects_date_range(self, tmp_path):
        data = tmp_path / "data"
        _seed_game(data, "2026-04-01", "old")
        _seed_game(data, "2026-04-10", "new")

        records = [
            r for r, _ in stream_game_analytics(
                str(data),
                pregame_min_cum_vol=5000,
                start_date="2026-04-05",
                end_date="2026-04-15",
            )
        ]
        assert [r["match_id"] for r in records] == ["new"]

    def test_no_cache_dir_does_not_create_files(self, tmp_path):
        data = tmp_path / "data"
        _seed_game(data, "2026-04-10", "g1")
        list(stream_game_analytics(str(data), pregame_min_cum_vol=5000))
        # No cache dir created since not provided
        assert not (tmp_path / "cache").exists()


class TestBaseRecordsCache:
    def test_miss_then_hit_skips_recompute(self, tmp_path, monkeypatch):
        data = tmp_path / "data"
        cache_dir = tmp_path / "cache"
        _seed_game(data, "2026-04-10", "g1")

        # Cold run: cache miss; manifest + pickle written.
        list(stream_game_analytics(
            str(data),
            pregame_min_cum_vol=5000,
            base_records_cache_dir=cache_dir,
        ))
        settings_hash = _base_records_settings_hash(5000.0, "vwap", 5)
        assert (cache_dir / f"{settings_hash}.pkl").exists()
        assert (cache_dir / f"{settings_hash}.manifest.json").exists()

        # Warm run: instrument _compute_base_record to verify it isn't called.
        calls = {"count": 0}
        real = analytics._compute_base_record

        def spy(*args, **kwargs):
            calls["count"] += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(analytics, "_compute_base_record", spy)
        results = list(stream_game_analytics(
            str(data),
            pregame_min_cum_vol=5000,
            base_records_cache_dir=cache_dir,
        ))
        assert calls["count"] == 0
        # Record still served correctly.
        assert results[0][0]["match_id"] == "g1"

    def test_fingerprint_change_invalidates_entry(self, tmp_path, monkeypatch):
        data = tmp_path / "data"
        cache_dir = tmp_path / "cache"
        _seed_game(data, "2026-04-10", "g1", fav_price=0.65)

        list(stream_game_analytics(
            str(data), pregame_min_cum_vol=5000, base_records_cache_dir=cache_dir,
        ))

        # Rewrite the trades file with different price -> mtime/size changes.
        _seed_game(data, "2026-04-10", "g1", fav_price=0.80)

        calls = {"count": 0}
        real = analytics._compute_base_record

        def spy(*args, **kwargs):
            calls["count"] += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(analytics, "_compute_base_record", spy)
        results = list(stream_game_analytics(
            str(data), pregame_min_cum_vol=5000, base_records_cache_dir=cache_dir,
        ))
        assert calls["count"] == 1
        assert results[0][0]["open_favorite_price"] == pytest.approx(0.80)

    def test_settings_change_uses_separate_cache_file(self, tmp_path):
        data = tmp_path / "data"
        cache_dir = tmp_path / "cache"
        _seed_game(data, "2026-04-10", "g1")

        list(stream_game_analytics(
            str(data), pregame_min_cum_vol=5000, base_records_cache_dir=cache_dir,
        ))
        list(stream_game_analytics(
            str(data),
            pregame_min_cum_vol=5000,
            open_anchor_window_min=10,
            base_records_cache_dir=cache_dir,
        ))
        # Two distinct settings hashes -> two pkl files.
        pkls = list(cache_dir.glob("*.pkl"))
        assert len(pkls) == 2

    def test_stale_entry_dropped_when_game_removed(self, tmp_path):
        data = tmp_path / "data"
        cache_dir = tmp_path / "cache"
        _seed_game(data, "2026-04-10", "g1")
        _seed_game(data, "2026-04-10", "g2")

        list(stream_game_analytics(
            str(data), pregame_min_cum_vol=5000, base_records_cache_dir=cache_dir,
        ))
        settings_hash = _base_records_settings_hash(5000.0, "vwap", 5)
        records_before, fp_before = _load_base_records_cache(cache_dir, settings_hash)
        assert len(records_before) == 2

        # Drop g2 from manifest + remove trades file. Modify g1 trades to force
        # cache_dirty so the prune path runs.
        date_dir = data / "2026-04-10"
        _write_manifest(date_dir / "manifest.json", [
            {
                "match_id": "g1",
                "sport": "nba",
                "status": "collected",
                "away_team": "Away",
                "home_team": "Home",
                "outcomes": ["Away", "Home"],
                "token_ids": ["g1-a", "g1-h"],
            }
        ])
        (date_dir / "g2_trades.json.gz").unlink()
        _seed_game(data, "2026-04-10", "g1", fav_price=0.70)  # triggers recompute

        list(stream_game_analytics(
            str(data), pregame_min_cum_vol=5000, base_records_cache_dir=cache_dir,
        ))
        records_after, fp_after = _load_base_records_cache(cache_dir, settings_hash)
        assert set(records_after.keys()) == {("2026-04-10", "g1")}
        assert set(fp_after.keys()) == {("2026-04-10", "g1")}

    def test_schema_version_mismatch_invalidates_cache(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        settings_hash = "deadbeef"
        # Write a manifest with the wrong schema version.
        (cache_dir / f"{settings_hash}.manifest.json").write_text(json.dumps({
            "schema_version": 999,
            "input_fingerprint_map": {"2026-04-10|g1": "x"},
        }))
        (cache_dir / f"{settings_hash}.pkl").write_bytes(b"junk-not-pickle")

        records, fps = _load_base_records_cache(cache_dir, settings_hash)
        assert records == {}
        assert fps == {}

    def test_save_load_roundtrip(self, tmp_path):
        cache_dir = tmp_path / "cache"
        settings_hash = _base_records_settings_hash(5000.0, "vwap", 5)
        records = {("2026-04-10", "g1"): {"match_id": "g1", "open_favorite_price": 0.6}}
        fingerprints = {("2026-04-10", "g1"): "fp-1"}
        _save_base_records_cache(cache_dir, settings_hash, records, fingerprints)

        loaded_records, loaded_fps = _load_base_records_cache(cache_dir, settings_hash)
        assert loaded_records == records
        assert loaded_fps == fingerprints
