# Polymarket Platform Outage Report

Audit of in-game trade gaps across the full collected corpus. Identifies periods where the Polymarket CLOB stopped recording trades during live games, causing missing in-game data that is invisible to standard quality checks.

**Audit date:** 2026-04-11
**Corpus:** 725 dates, 4,909 collected games (NBA: 2,753 / NHL: 1,274 / MLB: 882)

---

## Why this matters

When the Polymarket CLOB goes down, no trades are recorded on-chain. The pipeline collects everything available from Goldsky, so the resulting files look normal:

- `source: "goldsky"`
- `history_truncated: false`
- `trade_count` appears reasonable (pre-game + post-game trades are present)
- No entry in `download_log.json`

The only visible symptom is a long stretch of zero trades during what should be an active in-game period. Downstream analysis that relies on continuous in-game trading (price series, in-game volume metrics, live odds modeling) will silently produce wrong results unless these gaps are detected and handled.

---

## How the audit works

The script `scripts/audit_trade_gaps.py` reads every collected game's trades file and computes the largest gap between consecutive trades within the game window (`gamma_start_time` to `gamma_closed_time`).

A single game with a large gap could be low liquidity. A **platform outage** is identified when multiple games on the same date have gap start times that cluster within 15 minutes of each other, with average gaps exceeding 50 minutes. This cross-game correlation is the key signal — halftime breaks produce gaps at different times per game, while platform outages produce gaps at the same wall-clock time across all active markets.

### Detection criteria

| Signal | Normal halftime gap | Platform outage |
|---|---|---|
| Gap duration | 30-45 min | 50+ min (often 60-120+) |
| Gap start times across games | Scattered (each game has its own halftime) | Clustered within 15 min |
| Number of games affected | 1-2 | 3+ (often 5-15+) |
| Sports affected | Single sport | Often multiple sports |
| Gap position in game | Mid-game (halftime/intermission) | Any point, often Q3/Q4 or late innings |

---

## Corpus-wide findings

### Summary

| Metric | Value |
|---|---|
| Games scanned | 4,738 (of 4,909 collected; 171 skipped due to missing gamma times) |
| Games with any gap >= 30 min | 1,898 (mostly normal halftime/intermission) |
| Confirmed platform outage events | 50 |
| Total games affected by outages | 207 |
| Affected share of corpus | ~4.2% of collected games |

### Games flagged (>= 30 min gap) by sport

| Sport | Flagged | Total collected | Rate |
|---|---|---|---|
| NBA | 952 | 2,753 | 34.6% |
| MLB | 492 | 882 | 55.8% |
| NHL | 454 | 1,274 | 35.6% |

The high flag rates reflect natural game breaks (halftime, intermissions, rain delays), not outages. The confirmed outage rate after cross-game correlation filtering is much lower.

### Monthly outage distribution

| Month | Outage events | Games affected |
|---|---|---|
| 2024-10 | 1 | 4 |
| 2024-11 | 2 | 7 |
| 2024-12 | 4 | 13 |
| 2025-01 | 3 | 14 |
| 2025-02 | 4 | 18 |
| 2025-03 | 4 | 13 |
| 2025-04 | 3 | 13 |
| 2025-09 | 6 | 28 |
| 2025-10 | 5 | 17 |
| 2025-12 | 1 | 6 |
| 2026-03 | 17 | 74 |

March 2026 is the worst month by far, with 17 outage events affecting 74 games across all three sports.

### Largest confirmed outage events

| Date | Games | Avg gap | Sports | Window (UTC) |
|---|---|---|---|---|
| 2026-03-19 | 17 | 70 min | MLB, NBA, NHL | 01:14 - 02:46 |
| 2025-09-28 | 8 | 63 min | MLB | 21:53 - 00:28 |
| 2025-02-13 | 7 | 56 min | NBA | 04:09 - 05:37 |
| 2025-04-13 | 6 | 105 min | NBA | 22:23 - 00:55 |
| 2025-09-05 | 6 | 50 min | MLB | 02:27 - 03:48 |
| 2025-12-04 | 6 | 53 min | NHL | 03:08 - 04:39 |
| 2025-01-28 | 5 | 58 min | NBA | 03:38 - 05:08 |
| 2025-01-30 | 5 | 55 min | NBA | 03:48 - 05:06 |
| 2025-10-09 | 5 | 55 min | NBA, NHL | 03:05 - 04:45 |
| 2026-03-08 | 5 | 88 min | MLB | 20:07 - 22:20 |
| 2026-03-14 | 5 | 97 min | MLB | 22:58 - 01:15 |
| 2026-03-21 | 5 | 126 min | MLB | 22:44 - 02:44 |
| 2026-03-22 | 5 | 113 min | MLB, NHL | 23:09 - 02:57 |

---

## Case study: 2026-03-19

The largest single outage event. All 8 NBA games, plus NHL and MLB games active at the time, show a synchronized trade gap from ~01:17 to ~02:26 UTC (March 20).

**Discovery:** Investigating the Clippers vs Pelicans game (`nba-lac-nop-2026-03-19`) which showed 18,411 total trades but only 47 in-game trades during the second half. The same matchup played the night before (`nba-lac-nop-2026-03-18`) had 27,787 trades with continuous in-game coverage, confirming the gap is not game-specific.

**Impact on the Clippers-Pelicans game:**

| Metric | Actual (with outage) | Expected (based on 03-18 game) |
|---|---|---|
| In-game trades | 3,216 | ~10,000+ |
| In-game notional | ~$270K | ~$2.3M+ |
| Q3 + Q4 trades | ~0 | ~5,000+ |

The game events file has full coverage (109 events across all 4 quarters), confirming the game itself was not interrupted.

---

## Using the audit script

### Basic usage

```bash
# Find all games with in-game gaps >= 30 minutes (default)
python scripts/audit_trade_gaps.py

# Stricter threshold — only large gaps
python scripts/audit_trade_gaps.py --min-gap 3600

# Export all flagged games to CSV for analysis
python scripts/audit_trade_gaps.py --csv scripts/trade_gaps_report.csv

# Point at a different data directory
python scripts/audit_trade_gaps.py --data-dir /path/to/data/
```

### Output sections

1. **Audit summary** — counts of dates, games scanned, skips, errors
2. **Games with in-game trade gaps** — grouped by date, with per-game detail (gap duration, window, trade counts, source)
3. **Probable platform outages** — dates where multiple games share overlapping gaps (the strongest outage signal)

### CSV columns

| Column | Description |
|---|---|
| `date` | Game date (YYYY-MM-DD) |
| `match_id` | Game identifier |
| `sport` | nba / nhl / mlb |
| `trade_count` | Total trades in file |
| `ingame_trades` | Trades within gamma_start to gamma_closed |
| `gap_seconds` | Largest consecutive-trade gap during game (seconds) |
| `gap_minutes` | Same, in minutes |
| `gap_from_utc` | UTC timestamp where gap starts |
| `gap_to_utc` | UTC timestamp where gap ends |
| `source` | goldsky or data_api |
| `history_truncated` | Whether the file is flagged as truncated |

### Interpreting results

**Single game with a 30-45 min gap:** Almost certainly a normal halftime or intermission break. NBA halftime is ~18 min, but thin trading in the last minutes of Q2 and first minutes of Q3 can extend the gap to 30-45 min. Ignore unless correlated with other games.

**Single game with a 60+ min gap:** Could be a low-liquidity market or a single-market issue. Check trade count — very low total trades (< 200) suggests thin market, not outage.

**Multiple games on the same date with gaps starting within 15 min of each other:** Strong platform outage signal, especially if:
- Average gap exceeds 50 minutes
- Multiple sports are affected
- Total trades per game are otherwise healthy (1,000+)

### Downstream filtering

Games affected by platform outages can be identified programmatically using the CSV output:

```python
import csv
from collections import defaultdict
from datetime import datetime

# Load the gap report
with open("scripts/trade_gaps_report.csv") as f:
    gaps = list(csv.DictReader(f))

# Group by date and find tight clusters (gap starts within 15 min)
date_groups = defaultdict(list)
for g in gaps:
    date_groups[g["date"]].append(g)

outage_match_ids = set()
for date, games in date_groups.items():
    if len(games) < 3:
        continue
    # Sort by gap start time
    games.sort(key=lambda g: g["gap_from_utc"])
    cluster = [games[0]]
    for i in range(1, len(games)):
        t1 = datetime.strptime(cluster[-1]["gap_from_utc"], "%Y-%m-%d %H:%M")
        t2 = datetime.strptime(games[i]["gap_from_utc"], "%Y-%m-%d %H:%M")
        if abs((t2 - t1).total_seconds()) <= 900:
            cluster.append(games[i])
        else:
            if len(cluster) >= 3:
                outage_match_ids.update(g["match_id"] for g in cluster)
            cluster = [games[i]]
    if len(cluster) >= 3:
        outage_match_ids.update(g["match_id"] for g in cluster)

# Use in analysis: skip or flag these games
# outage_match_ids contains all match_ids affected by confirmed outages
```

---

## Limitations

- **False negatives for single-sport, single-game outages.** The cross-game correlation filter requires 3+ games with synchronized gaps. A brief outage affecting only one or two active markets will not be flagged as a platform outage.
- **Halftime boundary is fuzzy.** NBA/NHL halftime gaps naturally range from 25-45 min depending on market liquidity. The 50-min average threshold excludes most halftime gaps but may still include a few borderline cases.
- **Historical games have thinner markets.** Pre-2025 games often have fewer total trades, making natural gaps larger and harder to distinguish from outages.
- **The outage log is based on collected data only.** Games that were never collected (`status != "collected"`) are not analyzed. An outage that prevented collection entirely would not appear here.
- **Gamma time windows are approximate.** `gamma_start_time` is the scheduled start, not actual tipoff. This can be 5-30 min off, which shifts the in-game trade window slightly.
