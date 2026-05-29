#!/usr/bin/env python3
"""Backfill per-team in-game extremes sidecars for collected games.

Usage:
    python scripts/backfill_ingame_extremes.py \
        --data-dir data --cache-dir cache \
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] \
        [--force] [--dry-run]

Idempotent: a second invocation reports 0 written, N skipped unless --force.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _add_repo_to_path() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_add_repo_to_path()

from ingame_extremes import (  # noqa: E402
    INGAME_EXTREMES_SCHEMA_VERSION,
    compute_input_fingerprint,
    load_or_compute_ingame_extremes,
)
from loaders import build_loaded_game  # noqa: E402


def _iter_collected(data_dir: Path, start_date: str | None, end_date: str | None):
    for date_dir in sorted(data_dir.iterdir()):
        if not date_dir.is_dir():
            continue
        name = date_dir.name
        if start_date and name < start_date:
            continue
        if end_date and name > end_date:
            continue
        manifest_path = date_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            entries = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for entry in entries:
            if entry.get("status") != "collected":
                continue
            yield name, entry


def _sidecar_is_current(sidecar: Path, fingerprint: str) -> bool:
    if not sidecar.exists():
        return False
    try:
        payload = json.loads(sidecar.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == INGAME_EXTREMES_SCHEMA_VERSION
        and payload.get("input_fingerprint") == fingerprint
    )


def run(
    data_dir: Path,
    cache_dir: Path,
    start_date: str | None,
    end_date: str | None,
    force: bool,
    dry_run: bool,
) -> dict:
    t0 = time.time()
    scanned = 0
    written = 0
    skipped = 0
    failed: list[tuple[str, str, str]] = []

    for date, manifest in _iter_collected(data_dir, start_date, end_date):
        scanned += 1
        match_id = manifest.get("match_id")
        if not match_id:
            continue
        sidecar = cache_dir / date / f"{match_id}_ingame_extremes.json"
        fingerprint = compute_input_fingerprint(data_dir, date, match_id)

        if not force and _sidecar_is_current(sidecar, fingerprint):
            skipped += 1
            continue
        if dry_run:
            written += 1
            continue

        try:
            trades_path = data_dir / date / f"{match_id}_trades.json.gz"
            if not trades_path.exists():
                failed.append((date, match_id, "trades missing"))
                continue
            import gzip
            with gzip.open(trades_path, "rt", encoding="utf-8") as f:
                trades_data = json.load(f)
            game = build_loaded_game(str(data_dir), date, manifest, trades_data)
            # Force write: remove stale sidecar before load_or_compute (which would otherwise hit cache).
            if force and sidecar.exists():
                sidecar.unlink()
            load_or_compute_ingame_extremes(
                cache_dir, data_dir, date, match_id, game=game
            )
            written += 1
        except Exception as exc:  # pragma: no cover - defensive
            failed.append((date, match_id, str(exc)))

    elapsed = time.time() - t0
    print(
        f"[ingame_extremes] scanned={scanned} written={written} "
        f"skipped={skipped} failed={len(failed)} elapsed={elapsed:.2f}s"
        + (" (dry-run)" if dry_run else "")
    )
    for date, match_id, err in failed:
        print(f"  FAILED {date} {match_id}: {err}", file=sys.stderr)
    return {"scanned": scanned, "written": written, "skipped": skipped, "failed": failed}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--cache-dir", default="cache")
    p.add_argument("--start-date")
    p.add_argument("--end-date")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> dict:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    return run(
        data_dir=Path(args.data_dir),
        cache_dir=Path(args.cache_dir),
        start_date=args.start_date,
        end_date=args.end_date,
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
