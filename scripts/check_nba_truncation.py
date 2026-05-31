"""Audit NBA trade files for Data-API truncation that drops pre-game trades.

Goldsky pulls return full history; the Data API fallback is capped (~4000 trades)
and returns the *most recent* trades, so a high-volume game that fell back loses
its earliest trades — including the pre-game window used to set the open/tip-off
favorite and the entry price.

A game is "corrupted for tip-off analysis" when it is truncated AND has no
pre-game trades left (`has_pregame_trades == False`).

Usage:
    python scripts/check_nba_truncation.py [--data-dir data]
"""
from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path


def _scan_file(path: Path) -> dict | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    meta = d.get("price_checkpoints_meta", {}) or {}
    pc = d.get("price_checkpoints", {}) or {}
    any_last_pregame = any(
        v.get("last_pregame_trade_price") is not None for v in pc.values()
    )
    return {
        "history_source": d.get("history_source"),
        "history_truncated": bool(d.get("history_truncated")),
        "history_cap": d.get("history_cap"),
        "trade_count": d.get("trade_count", len(d.get("trades", []))),
        "fallback_used": bool(meta.get("fallback_used")),
        "has_pregame_trades": meta.get("has_pregame_trades"),
        "any_last_pregame_price": any_last_pregame,
        "price_quality": meta.get("price_quality"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()

    base = Path(args.data_dir)
    files = sorted(base.glob("*/nba-*_trades.json.gz"))
    total = len(files)
    print(f"Scanning {total} NBA trade files under {base}/ ...")

    n = 0
    truncated = 0
    fallback = 0
    goldsky = 0
    missing_pregame = 0
    corrupted = 0          # truncated AND no pregame trades left
    at_or_over_cap = 0
    trunc_dates: Counter = Counter()
    src_counts: Counter = Counter()

    for i, path in enumerate(files, 1):
        rec = _scan_file(path)
        if rec is None:
            continue
        n += 1
        src_counts[rec["history_source"]] += 1
        if rec["history_source"] == "goldsky":
            goldsky += 1
        if rec["fallback_used"] or rec["history_source"] == "data_api":
            fallback += 1
        if rec["history_truncated"]:
            truncated += 1
            trunc_dates[path.parent.name] += 1
        if rec["has_pregame_trades"] is False:
            missing_pregame += 1
        if rec["history_truncated"] and rec["has_pregame_trades"] is False:
            corrupted += 1
        cap = rec["history_cap"] or 4000
        if rec["trade_count"] and rec["trade_count"] >= cap:
            at_or_over_cap += 1
        if i % 500 == 0:
            print(f"  ...{i}/{total}")

    def pct(x: int) -> str:
        return f"{x} ({100*x/n:.1f}%)" if n else "0"

    print(f"\n=== NBA truncation audit ({n} readable games) ===")
    print(f"history_source breakdown      : {dict(src_counts)}")
    print(f"goldsky (full history, uncapped): {pct(goldsky)}")
    print(f"history_source == data_api    : {pct(src_counts.get('data_api', 0))}")
    print(f"history_truncated == True     : {pct(truncated)}  <- TRADES actually cut")
    print(f"CORRUPTED (trunc & no pregame) : {pct(corrupted)}  <- unusable for tip-off bands")
    print(f"trade_count >= cap (mostly OK goldsky): {pct(at_or_over_cap)}")
    print(f"has_pregame_trades False (any cause)  : {pct(missing_pregame)}")
    print(f"  meta.fallback_used (OPENING-price checkpoint fallback, NOT truncation): {pct(fallback)}")
    if trunc_dates:
        ds = sorted(trunc_dates)
        print(f"\nTruncated games span {ds[0]} .. {ds[-1]} across {len(trunc_dates)} dates")


if __name__ == "__main__":
    main()
