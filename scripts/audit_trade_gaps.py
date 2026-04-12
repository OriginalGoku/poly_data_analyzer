#!/usr/bin/env python3
"""Scan all collected games for suspicious in-game trade gaps.

Reads every manifest.json under data/, opens the trades file for each
collected game that has gamma_start_time / gamma_closed_time, and reports
the largest consecutive-trade gap that falls within the game window.

Usage:
    python scripts/audit_trade_gaps.py [--min-gap 1800] [--data-dir data/] [--csv gaps.csv]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def parse_iso_ts(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(
            datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        )
    except ValueError:
        return None


def find_largest_ingame_gap(
    trades: list[dict], game_start_ts: int, game_end_ts: int
) -> tuple[int, int, int, int]:
    """Return (gap_seconds, gap_from_ts, gap_to_ts, ingame_trade_count)."""
    ingame_ts = sorted(
        int(t["timestamp"])
        for t in trades
        if game_start_ts <= int(t["timestamp"]) <= game_end_ts
    )

    if len(ingame_ts) < 2:
        return (0, 0, 0, len(ingame_ts))

    max_gap = 0
    gap_from = gap_to = 0
    for i in range(1, len(ingame_ts)):
        g = ingame_ts[i] - ingame_ts[i - 1]
        if g > max_gap:
            max_gap = g
            gap_from = ingame_ts[i - 1]
            gap_to = ingame_ts[i]

    return (max_gap, gap_from, gap_to, len(ingame_ts))


def ts_to_utc_str(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-gap",
        type=int,
        default=1800,
        help="Minimum gap in seconds to report (default: 1800 = 30 min)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/",
        help="Root data directory (default: data/)",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Write results to a CSV file",
    )
    args = parser.parse_args()

    data_root = Path(args.data_dir)
    if not data_root.is_dir():
        print(f"Error: {data_root} is not a directory", file=sys.stderr)
        sys.exit(1)

    min_gap = args.min_gap
    results: list[dict] = []
    dates_scanned = 0
    games_scanned = 0
    skipped_no_times = 0
    skipped_no_file = 0
    errors = 0

    date_dirs = sorted(
        d for d in data_root.iterdir() if d.is_dir() and (d / "manifest.json").exists()
    )

    for date_dir in date_dirs:
        dates_scanned += 1
        manifest_path = date_dir / "manifest.json"

        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  WARN: {manifest_path}: {e}", file=sys.stderr)
            errors += 1
            continue

        for entry in manifest:
            if entry.get("status") != "collected":
                continue

            match_id = entry["match_id"]
            gamma_start = parse_iso_ts(entry.get("gamma_start_time", ""))
            gamma_closed = parse_iso_ts(entry.get("gamma_closed_time", ""))

            if gamma_start is None or gamma_closed is None:
                skipped_no_times += 1
                continue

            trades_path = date_dir / f"{match_id}_trades.json.gz"
            if not trades_path.exists():
                trades_path = date_dir / f"{match_id}_trades.json"
                if not trades_path.exists():
                    skipped_no_file += 1
                    continue

            games_scanned += 1

            try:
                opener = gzip.open if str(trades_path).endswith(".gz") else open
                with opener(trades_path, "rt", encoding="utf-8") as f:
                    data = json.load(f)
                trades = data.get("trades", [])
            except (json.JSONDecodeError, OSError, gzip.BadGzipFile) as e:
                print(f"  WARN: {trades_path}: {e}", file=sys.stderr)
                errors += 1
                continue

            gap_secs, gap_from, gap_to, ingame_count = find_largest_ingame_gap(
                trades, gamma_start, gamma_closed
            )

            if gap_secs >= min_gap:
                results.append(
                    {
                        "date": date_dir.name,
                        "match_id": match_id,
                        "sport": entry.get("sport", ""),
                        "trade_count": len(trades),
                        "ingame_trades": ingame_count,
                        "gap_seconds": gap_secs,
                        "gap_minutes": round(gap_secs / 60, 1),
                        "gap_from_utc": ts_to_utc_str(gap_from),
                        "gap_to_utc": ts_to_utc_str(gap_to),
                        "source": data.get("source", ""),
                        "history_truncated": data.get("history_truncated", False),
                    }
                )

    # Print summary
    print(f"\nAudit complete:")
    print(f"  Dates scanned:    {dates_scanned}")
    print(f"  Games scanned:    {games_scanned}")
    print(f"  Skipped (no times): {skipped_no_times}")
    print(f"  Skipped (no file):  {skipped_no_file}")
    print(f"  Errors:           {errors}")
    print(f"  Gaps >= {min_gap}s:     {len(results)}")

    if not results:
        print(f"\nNo in-game trade gaps >= {min_gap}s found.")
        return

    # Group by date+gap window to detect platform-wide outages
    date_gaps: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        date_gaps[r["date"]].append(r)

    print(f"\n{'='*90}")
    print("GAMES WITH IN-GAME TRADE GAPS")
    print(f"{'='*90}")

    for date in sorted(date_gaps):
        games = date_gaps[date]
        sports = set(g["sport"] for g in games)

        # Check if gaps overlap (platform-wide outage signal)
        gap_starts = [
            datetime.strptime(g["gap_from_utc"], "%Y-%m-%d %H:%M")
            for g in games
        ]
        gap_ends = [
            datetime.strptime(g["gap_to_utc"], "%Y-%m-%d %H:%M")
            for g in games
        ]
        overlap_start = max(gap_starts)
        overlap_end = min(gap_ends)
        is_platform_outage = len(games) > 1 and overlap_start < overlap_end

        print(f"\n--- {date} ({len(games)} games, sports: {', '.join(sorted(sports))}) ---")
        if is_platform_outage:
            print(
                f"  ** PLATFORM OUTAGE: {len(games)} games share overlapping gap "
                f"{overlap_start.strftime('%H:%M')}-{overlap_end.strftime('%H:%M')} UTC **"
            )

        for g in sorted(games, key=lambda x: x["gap_seconds"], reverse=True):
            print(
                f"  {g['match_id']:<45} "
                f"{g['gap_minutes']:>6.1f}min  "
                f"{g['gap_from_utc'][-5:]}-{g['gap_to_utc'][-5:]} UTC  "
                f"trades={g['trade_count']:>6}  "
                f"ingame={g['ingame_trades']:>5}  "
                f"src={g['source']}"
            )

    # Platform outage summary
    outage_dates = [
        (date, games)
        for date, games in date_gaps.items()
        if len(games) > 1
    ]
    if outage_dates:
        print(f"\n{'='*90}")
        print("PROBABLE PLATFORM OUTAGES (multiple games with overlapping gaps)")
        print(f"{'='*90}")
        for date, games in sorted(outage_dates):
            sports = set(g["sport"] for g in games)
            avg_gap = sum(g["gap_minutes"] for g in games) / len(games)
            print(
                f"  {date}: {len(games)} games affected, "
                f"avg gap {avg_gap:.0f}min, "
                f"sports: {', '.join(sorted(sports))}"
            )

    # CSV output
    if args.csv:
        fieldnames = [
            "date", "match_id", "sport", "trade_count", "ingame_trades",
            "gap_seconds", "gap_minutes", "gap_from_utc", "gap_to_utc",
            "source", "history_truncated",
        ]
        with open(args.csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sorted(results, key=lambda r: (r["date"], r["match_id"])))
        print(f"\nCSV written to {args.csv}")


if __name__ == "__main__":
    main()
