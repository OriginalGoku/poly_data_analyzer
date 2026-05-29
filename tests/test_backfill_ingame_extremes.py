"""Tests for scripts/backfill_ingame_extremes.py."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backfill_ingame_extremes import main


def _manifest(match_id: str) -> dict:
    return {
        "match_id": match_id,
        "sport": "nba",
        "status": "collected",
        "away_team": "A",
        "home_team": "H",
        "outcomes": ["A", "H"],
        "token_ids": [f"{match_id}-toka", f"{match_id}-tokh"],
        "gamma_start_time": "2026-04-10T19:00:00Z",
        "gamma_closed_time": "2026-04-10T22:00:00Z",
    }


def _write_trades(path: Path, token_a: str, token_h: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "trades": [
            {"timestamp": 1712772100, "asset": token_a, "price": 0.55, "size": 10},
            {"timestamp": 1712772300, "asset": token_h, "price": 0.30, "size": 5},
        ]
    }
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)


def _write_events(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        {"team_tricode": "A", "away_score": 2, "home_score": 0, "time_actual": "2026-04-10T19:01:00Z"},
        {"team_tricode": "H", "away_score": 2, "home_score": 2, "time_actual": "2026-04-10T19:30:00Z"},
    ]
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"events": events}, f)


def _build_date_dir(data_dir: Path, date: str, match_ids: list[str]) -> None:
    base = data_dir / date
    base.mkdir(parents=True, exist_ok=True)
    manifests = [_manifest(m) for m in match_ids]
    (base / "manifest.json").write_text(json.dumps(manifests))
    for m in match_ids:
        _write_trades(base / f"{m}_trades.json.gz", f"{m}-toka", f"{m}-tokh")
        _write_events(base / f"{m}_events.json.gz")


def _argv(data_dir: Path, cache_dir: Path, **extras) -> list[str]:
    argv = ["--data-dir", str(data_dir), "--cache-dir", str(cache_dir)]
    for k, v in extras.items():
        flag = "--" + k.replace("_", "-")
        if v is True:
            argv.append(flag)
        elif v is not None:
            argv += [flag, str(v)]
    return argv


def test_writes_sidecars_on_first_run(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _build_date_dir(data_dir, "2026-04-10", ["g1", "g2"])

    result = main(_argv(data_dir, cache_dir))

    assert result["scanned"] == 2
    assert result["written"] == 2
    assert result["skipped"] == 0
    assert (cache_dir / "2026-04-10" / "g1_ingame_extremes.json").exists()
    assert (cache_dir / "2026-04-10" / "g2_ingame_extremes.json").exists()


def test_idempotent_second_run_skips(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _build_date_dir(data_dir, "2026-04-10", ["g1", "g2"])
    main(_argv(data_dir, cache_dir))

    result = main(_argv(data_dir, cache_dir))
    assert result["scanned"] == 2
    assert result["written"] == 0
    assert result["skipped"] == 2


def test_force_regenerates_regardless(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _build_date_dir(data_dir, "2026-04-10", ["g1"])
    main(_argv(data_dir, cache_dir))

    result = main(_argv(data_dir, cache_dir, force=True))
    assert result["written"] == 1
    assert result["skipped"] == 0


def test_dry_run_writes_nothing(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _build_date_dir(data_dir, "2026-04-10", ["g1"])

    result = main(_argv(data_dir, cache_dir, dry_run=True))
    assert result["scanned"] == 1
    assert result["written"] == 1  # reported as would-write
    assert not (cache_dir / "2026-04-10" / "g1_ingame_extremes.json").exists()


def test_date_range_filters(tmp_path):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    _build_date_dir(data_dir, "2026-04-10", ["g1"])
    _build_date_dir(data_dir, "2026-04-12", ["g2"])

    result = main(_argv(data_dir, cache_dir, start_date="2026-04-11", end_date="2026-04-15"))
    assert result["scanned"] == 1
    assert result["written"] == 1
    assert (cache_dir / "2026-04-12" / "g2_ingame_extremes.json").exists()
    assert not (cache_dir / "2026-04-10").exists()
