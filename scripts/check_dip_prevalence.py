#!/usr/bin/env python3
"""Scan collected games for in-game favorite/underdog probability dips.

Reports how often either token trades below fixed absolute thresholds during
in-game trading windows defined by play-by-play event timestamps.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


DEFAULT_THRESHOLDS = (0.05, 0.04, 0.03, 0.02)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Archive root containing YYYY-MM-DD directories (default: data)",
    )
    parser.add_argument(
        "--threshold",
        dest="thresholds",
        type=float,
        action="append",
        default=None,
        help="Absolute probability threshold to check. May be repeated.",
    )
    return parser.parse_args()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_json(path: Path) -> dict:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def iter_date_dirs(data_root: Path):
    for date_dir in sorted(data_root.iterdir()):
        if not date_dir.is_dir():
            continue
        manifest_path = date_dir / "manifest.json"
        if manifest_path.exists():
            yield date_dir, manifest_path


def main() -> None:
    args = parse_args()
    data_root = Path(args.data_dir)
    if not data_root.is_dir():
        raise SystemExit(f"{data_root} is not a directory")

    thresholds = tuple(sorted(set(args.thresholds or DEFAULT_THRESHOLDS), reverse=True))
    stats = {
        threshold: {
            "games": 0,
            "events": 0,
            "games_by_sport": defaultdict(int),
        }
        for threshold in thresholds
    }
    totals = {
        "dates": 0,
        "collected_games": 0,
        "games_with_events": 0,
        "games_with_ingame_trades": 0,
        "skipped_missing_events": 0,
        "skipped_missing_trades": 0,
    }

    for date_dir, manifest_path in iter_date_dirs(data_root):
        totals["dates"] += 1
        with open(manifest_path, encoding="utf-8") as handle:
            entries = json.load(handle)

        for manifest in entries:
            if manifest.get("status") != "collected":
                continue
            totals["collected_games"] += 1
            match_id = manifest["match_id"]
            trades_path = date_dir / f"{match_id}_trades.json.gz"
            if not trades_path.exists():
                trades_path = date_dir / f"{match_id}_trades.json"
            events_path = date_dir / f"{match_id}_events.json.gz"
            if not events_path.exists():
                events_path = date_dir / f"{match_id}_events.json"

            if not trades_path.exists():
                totals["skipped_missing_trades"] += 1
                continue
            if not events_path.exists():
                totals["skipped_missing_events"] += 1
                continue

            events_payload = load_json(events_path)
            events = events_payload.get("events", []) or []
            event_times = [
                parse_iso(event.get("time_actual"))
                for event in events
                if event.get("away_score") is not None and event.get("home_score") is not None
            ]
            event_times = [event_time for event_time in event_times if event_time is not None]
            if not event_times:
                totals["skipped_missing_events"] += 1
                continue

            totals["games_with_events"] += 1
            game_start = min(event_times).timestamp()
            game_end = max(event_times).timestamp()

            trades_payload = load_json(trades_path)
            trades = trades_payload.get("trades", []) or []
            ingame_trades = [
                trade
                for trade in trades
                if game_start <= int(trade.get("timestamp", 0)) <= game_end
            ]
            if not ingame_trades:
                continue

            totals["games_with_ingame_trades"] += 1
            prices = [float(trade["price"]) for trade in ingame_trades if trade.get("price") is not None]
            sport = manifest.get("sport", "unknown")

            for threshold in thresholds:
                threshold_events = sum(1 for price in prices if price <= threshold)
                if threshold_events == 0:
                    continue
                stats[threshold]["games"] += 1
                stats[threshold]["events"] += threshold_events
                stats[threshold]["games_by_sport"][sport] += 1

    print("Dip prevalence audit")
    print("===================")
    print(f"Dates scanned:               {totals['dates']}")
    print(f"Collected games:             {totals['collected_games']}")
    print(f"Games with score events:     {totals['games_with_events']}")
    print(f"Games with in-game trades:   {totals['games_with_ingame_trades']}")
    print(f"Skipped missing events:      {totals['skipped_missing_events']}")
    print(f"Skipped missing trades:      {totals['skipped_missing_trades']}")
    print()
    print(
        f"{'threshold':>10}  {'games':>8}  {'dip_events':>10}  {'avg/game':>8}  sports"
    )
    for threshold in thresholds:
        games = stats[threshold]["games"]
        events = stats[threshold]["events"]
        avg = events / games if games else 0.0
        sports = ", ".join(
            f"{sport}:{count}"
            for sport, count in sorted(stats[threshold]["games_by_sport"].items())
        ) or "-"
        print(
            f"{threshold:>10.2%}  {games:>8}  {events:>10}  {avg:>8.2f}  {sports}"
        )


if __name__ == "__main__":
    main()
