# Data Specification

Reference for the data produced by `poly-data-downloader`. Intended as the handoff contract for a downstream analysis repo.

---

## Directory Layout

```
data/
└── YYYY-MM-DD/
    ├── manifest.json               # index of all games for the date
    ├── {match_id}_trades.json      # one file per collected game
    └── {match_id}_events.json      # one file per collected game (if available)
```

`match_id` format varies by era:

| Pattern | Example | When |
|---|---|---|
| `{sport}-{away}-{home}-{YYYY-MM-DD}` | `nhl-car-bos-2025-11-14` | Modern games (standard) |
| `{sport}-{away}-{home}-{YYYY-MM-DD}-g2` | `mlb-nyy-bos-2025-08-05-g2` | MLB double-headers |
| `nba-play-in-{teams}` | `nba-play-in-lakers-vs-pelicans` | Historical NBA Play-In (Apr 2024) |
| `nba-dailies-{YYYY-MM-DD}` | `nba-dailies-2024-04-20` | Historical NBA dailies bundle |
| `nba-dailies-{YYYY-MM-DD}-{hex}` | `nba-dailies-2024-04-20-0x38eaa24642` | Historical NBA dailies sub-market |
| `nba-finals-{slug}` | `nba-finals-thunder-vs-pacers` | Historical NBA Finals |
| `nba-preseason-{slug}` | `nba-preseason-lakers-vs-warriors` | Historical NBA preseason |

Historical match IDs are derived from Gamma event slugs and do not follow the modern `{sport}-{away}-{home}-{date}` convention. A small number of legacy entries also have a `nbanba-` prefix typo from historical slug extraction.

---

## 1. Manifest (`manifest.json`)

Array of entries — one per game found by `scan`. Two shapes depending on whether a Polymarket market was found.

### 1a. Matched Entry (has Polymarket data)

```jsonc
{
  // --- Identity ---
  "match_id": "nhl-car-bos-2025-11-14",   // primary key; used as filename prefix
  "sport": "nhl",                           // "nhl" | "mlb" | "nba" | "soccer" | …
  "sports_api_id": "2024020312",            // numeric ID from the sports league API when available; some historical_gamma_title and historical_nba_summer_league entries still leave this empty

  // --- Teams ---
  "home_team": "Bruins",                    // full team name from league API
  "away_team": "Hurricanes",
  "is_final": true,                         // game has finished per league API

  // --- Polymarket linkage ---
  "polymarket_matched": true,
  "event_slug": "nhl-car-bos-2025-11-14",  // Gamma event slug (may differ from match_id)
  "event_id": "521087",                     // Gamma numeric event ID (string)
  "condition_id": "0xabc…",                // CLOB condition ID (hex string)
  "token_ids": ["0x111…", "0x222…"],       // [away_token_id, home_token_id] — always length 2
  "outcomes": ["Hurricanes", "Bruins"],     // outcome labels matching token_ids order
  "question": "NHL: CAR vs BOS?",          // Polymarket market question text
  "gamma_start_time": "2025-11-14T23:00:00Z",  // scheduled start per Gamma (ISO 8601 UTC)
  "gamma_closed_time": "2025-11-15T02:30:00Z", // market close time per Gamma (ISO 8601 UTC; "" if still open)

  // --- Pipeline state ---
  "status": "collected",                    // see Status Values below
  "match_method": "slug",                   // how Polymarket was found (see Match Methods)

  // --- Derived trade summary (collected entries only) ---
  "volume_stats": {
    "trade_count": 843,                     // count of normalized trades in {match_id}_trades.json
    "total_notional_usdc": 10492.41,        // sum(size) across all trades
    "buy_notional_usdc": 5332.16,           // sum(size) where side == "BUY"
    "sell_notional_usdc": 5160.25,          // sum(size) where side == "SELL"
    "median_trade_size_usdc": 8.5,
    "mean_trade_size_usdc": 12.45,
    "max_trade_size_usdc": 250.0,
    "first_trade_ts": 1763152200,           // Unix seconds (UTC)
    "last_trade_ts": 1763165700,
    "pre_game_notional_usdc": 4821.7,       // null if gamma_start_time unavailable
    "in_game_notional_usdc": 5470.71,       // null if gamma_start_time unavailable
    "post_game_notional_usdc": 200.0        // null if gamma_closed_time unavailable
  },

  // --- Price checkpoint coverage summary (collected entries only) ---
  "price_checkpoint_coverage": {
    "clob_succeeded_count": 1,    // number of tokens with non-empty CLOB price history
    "has_early_price_count": 2,   // number of tokens with any early price (CLOB or trade-derived)
    "total_tokens": 2,
    "best_source": "clob_open"    // "clob_open" | "first_pregame_trade" | "first_trade" | "unavailable"
  }
}
```

### 1b. Unmatched Entry (no Polymarket market found)

```jsonc
{
  "match_id": "nhl-ott-buf-2025-11-14",
  "sport": "nhl",
  "sports_api_id": "2024020311",
  "home_team": "Sabres",
  "away_team": "Senators",
  "is_final": true,
  "polymarket_matched": false,
  "status": "scanned"
  // No Polymarket fields present
}
```

### Status Values

| Status | Terminal? | Meaning |
|---|---|---|
| `scanned` | No | Found by scan, not yet pulled |
| `collected` | Yes | Trades + events written to disk |
| `no_trades` | No | 0 trades from all sources; eligible for retry |
| `no_trades_final` | Yes | Still 0 trades after backfill retries |
| `needs_classification` | Yes | Manual review required |

Backfill skips entries already in a terminal status, so re-running is safe.

### Optional Fields (added conditionally)

| Field | When present | Values |
|---|---|---|
| `events_status` | NBA only, incremental runs | `"missing_403"` — CDN blocked play-by-play fetch; written by `pull`, **not durable if scan is re-run after collection**. Not present in clean full-rebuild datasets |
| `no_trade_attempts` | After retry on incremental runs | Integer count of failed trade fetch attempts. Not present in clean full-rebuild datasets |
| `volume_stats` | Collected entries only | Compact trade-volume summary derived from the saved trades file for downstream filtering |
| `price_checkpoint_coverage` | Collected entries only | Summary of early-price data quality for downstream filtering without loading trades files |

### Match Methods

| Value | Description |
|---|---|
| `slug` | Direct slug lookup matched on game date |
| `slug_next_day` | Slug matched on date+1 (common for late NHL/NBA games) |
| `tag_time_filter` | Slug missed; matched via Gamma tag + team name comparison |
| `historical_gamma_title` | Older NBA event discovered from Gamma tags/title parsing instead of a league schedule |
| `historical_nba_summer_league` | July 2025 NBA historical row that is collectible from Polymarket but outside the currently supported NBA ID / PBP enrichment path |
| `historical_mlb_postseason` | Supported historical MLB market discovered in the late-2024 postseason / end-of-season window |
| `historical_unclassified` | Older Gamma-discovered NBA event that needs manual review before collection |
| `mlb_spring_training_unmatched` | Final unmatched MLB Spring Training / exhibition row that is intentionally outside current production support |
| `nhl_opening_week_unmatched` | Final unmatched NHL opening-week row kept for audit visibility but outside current supported collection coverage |
| `nhl_international_unmatched` | Final unmatched NHL international/Olympic-style row outside standard NHL club-game support |
| `nba_special_event_unmatched` | Final unmatched NBA special-event row (e.g. All-Star style teams) outside standard NBA game support |

---

## 2. Trades File (`{match_id}_trades.json`)

```jsonc
{
  // --- Header ---
  "match_id": "nhl-car-bos-2025-11-14",
  "sport": "nhl",
  "condition_id": "0xabc…",
  "question": "NHL: CAR vs BOS?",
  "outcomes": ["Hurricanes", "Bruins"],     // order matches token_ids
  "token_ids": ["0x111…", "0x222…"],

  // --- Source metadata ---
  "source": "goldsky",                      // "goldsky" | "data_api" (see Source section)
  "history_source": "goldsky",              // explicit provenance for the saved history
  "history_truncated": false,               // true when fallback likely hit the server cap
  "history_cap": null,                      // integer cap for truncated fallback files (e.g. 4000)
  "opening_source": "clob",                 // "clob" | "none" (see notes below)
  "trade_count": 843,                       // length of trades array

  // --- Opening odds (backward-compat field) ---
  // opening_odds[tid] == price_checkpoints[tid]["selected_early_price"]
  // Prefer price_checkpoints for new analysis — opening_odds is kept for backward compatibility.
  "opening_odds": {
    "0x111…": 0.47,                         // best available early price for this token (see price_checkpoints)
    "0x222…": 0.53                          // null only when no data at all (CLOB failed and no trades)
  },

  // --- Price checkpoints (structured early-price data, v2+) ---
  "price_checkpoints": {
    "0x111…": {
      "clob_open": 0.47,                    // first CLOB price-history point; null if CLOB fetch failed
      "first_trade_price": 0.45,            // price of the first on-chain trade for this token; null if no trades
      "first_pregame_trade_price": 0.46,    // first trade before gamma_start_time; null if unavailable
      "last_pregame_trade_price": 0.49,     // last trade before gamma_start_time; null if unavailable
      "selected_early_price": 0.47,         // best available early price (see selection priority below)
      "selected_early_price_source": "clob_open"  // see source enum below
    },
    "0x222…": { /* same structure */ }
  },
  "price_checkpoints_meta": {
    "clob_succeeded": true,                 // true if CLOB history was non-empty for at least one token
    "clob_history_len": 142,               // total price-history points across all tokens
    "fallback_used": false,                 // true when no CLOB data was available
    "has_pregame_trades": true,             // true if any trade exists before gamma_start_time
    "market_opened_before_coverage": false, // true if start is known but there is no data at all
    "price_quality": "exact"               // "exact" | "inferred" | "unavailable" (see enum below)
  },

  // --- Trades ---
  "trades": [
    {
      "side": "BUY",                        // "BUY" | "SELL" — relative to the token (asset field)
      "asset": "0x111…",                    // token_id this trade is for
      "price": 0.46,                        // executed price in USDC per token share (0–1 range)
      "size": 125.50,                       // USDC notional value of the trade
      "timestamp": 1731632400,              // Unix timestamp (seconds, UTC)
      "transactionHash": "0xdef…"           // on-chain transaction hash
    }
    // … sorted by timestamp ascending
  ]
}
```

#### Notes on `side`
- `BUY` = someone bought the token (betting that outcome wins)
- `SELL` = someone sold the token (exiting a position)
- Both sides are present in the trade log. For price-series analysis, use all trades regardless of side.

#### Notes on `price`
- Represents probability: `0.0` = market says 0% chance, `1.0` = certainty
- Prices are derived from on-chain fills and can have floating-point artifacts near 0 and 1 (expect values like `0.9999999982` instead of `1.0`)
- Both tokens' prices at any point in time should sum to ~1.0, but small deviations occur (up to ±0.05 during illiquid periods)

#### Notes on `opening_odds`
- **Retained for backward compatibility.** `opening_odds[tid]` equals `price_checkpoints[tid]["selected_early_price"]`.
- For new analysis, use `price_checkpoints` — it exposes the source, CLOB and trade-derived checkpoints separately, and collection-quality metadata.
- `opening_odds` is `null` only when there is no data at all (CLOB failed and no trades collected). It is no longer null simply because CLOB was unavailable.
- `opening_source = "clob"` means the selected price came from CLOB order-book history. `"none"` means the price is trade-derived or completely unavailable.

#### Price checkpoint selection priority

| Priority | `selected_early_price_source` | Meaning |
|---|---|---|
| 1 (best) | `clob_open` | First point from CLOB price history (order-book accuracy) |
| 2 | `first_pregame_trade` | First on-chain trade before `gamma_start_time` |
| 3 | `first_trade` | First on-chain trade regardless of timing |
| 4 (worst) | `unavailable` | No price data found for this token |

#### `price_quality` enum

| Value | Meaning |
|---|---|
| `exact` | At least one token has `clob_open` price |
| `inferred` | Best available price is trade-derived (no CLOB data) |
| `unavailable` | No early price found for any token |

#### `best_source` in `price_checkpoint_coverage` (manifest)

Reports the highest-priority source found across all tokens for this game. Use this field to filter games in downstream analysis without loading the full trades file.

#### Source field

| Value | Data source | Coverage |
|---|---|---|
| `"goldsky"` | Goldsky subgraph (on-chain indexer) | Complete — all trades ever made |
| `"data_api"` | Polymarket Data API | **Server-capped at ~4000 trades in live testing** — truncated for high-volume markets |

The pipeline tries Goldsky first and falls back to `data_api` only when Goldsky returns 0 trades. If `source = "data_api"` and `trade_count` is near 4000, the trade history is likely truncated — earliest trades may be missing.

> **Important:** this cap is an upstream API constraint, not just a local config choice. Official Polymarket `/trades` documentation and changelog entries disagree on the exact `limit`/`offset` maxima, but live requests currently reject historical offsets beyond `3000` with `max historical activity offset of 3000 exceeded`.

Both sources produce the same field schema: rows with invalid `timestamp`, `side`, `asset`, `price`, or `size` are dropped during normalization and will not appear in the trades array. The schema guarantees for all fields are identical regardless of source.

#### Notes on provenance fields
- `history_source` is the authoritative source of the saved trade history (`goldsky` or `data_api`)
- `history_truncated = true` means the file should be treated as partial history rather than as proof of a late-open market
- `history_cap` is only populated for fallback files and records the practical server cap used during collection
- `opening_source = "clob"` means `opening_odds` / `selected_early_price` came from the CLOB price-history endpoint; `"none"` means trade-derived or unavailable
- All current data files contain `price_checkpoints` and `price_checkpoints_meta`; if you encounter files without these keys from an older collection run, treat them as absent when loading

---

## 3. Events File (`{match_id}_events.json`)

Present for all collected games **except** NBA games where the play-by-play CDN returned 403. Also written for `no_trades` games if event data was successfully fetched.

> **Detecting missing events:** Do not filter by `events_status: "missing_403"` in the manifest — that field is not durable across re-scans (see [Optional Fields](#optional-fields-added-conditionally)). Use file existence instead: `(date_dir / f"{match_id}_events.json").exists()`.

```jsonc
{
  // --- Header ---
  "match_id": "nhl-car-bos-2025-11-14",
  "sport": "nhl",
  "team1": "Hurricanes",                    // away team (game visitor)
  "team2": "Bruins",                        // home team
  "game_date": "2025-11-14",
  "sports_api_id": "2024020312",
  "event_count": 31,                        // length of events array

  "events": [ … ]                           // sport-specific, see below
}
```

### 3a. NHL Events

Only goals and structural markers are captured — no shots, penalties, or faceoffs.

```jsonc
// Structural marker
{
  "event_type": "period-start",     // "period-start" | "period-end" | "game-end"
  "period": 1,                      // 1–3 = regulation, 4 = OT, 5 = shootout
  "period_type": "REG",             // "REG" | "OT" | "SO"
  "time_in_period": "00:00"         // "MM:SS" format
}

// Goal event
{
  "event_type": "goal",
  "period": 2,
  "period_type": "REG",
  "time_in_period": "14:32",
  "home_score": 2,                  // cumulative score after this goal
  "away_score": 1,
  "scoring_team": "Hurricanes",     // full team name from manifest — matches team1/team2 in events file header, not a tricode ("UNK" if unresolvable)
  "description": "goal"             // always "goal" (from API typeDescKey)
}
```

> **`scoring_team` is a full team name, not a tricode.** To get the tricode, cross-reference with `home_team`/`away_team` from the manifest entry.

Events are sorted by `(period, time_in_period_as_seconds)`.
Shootout goals: scores freeze at the tied value in play-by-play; use `scoring_team` + last `period_type == "SO"` goal to determine winner.

### 3b. MLB Events

Only scoring plays are captured (hits, walks, errors that advance runners to score). Non-scoring at-bats are omitted.

```jsonc
// Scoring play
{
  "event_type": "Home Run",         // MLB result event name (free text from API)
  "inning": 3,                      // 1-indexed inning number
  "half_inning": "top",             // "top" (away bats) | "bottom" (home bats)
  "timestamp": "2025-09-05T19:42:30Z",  // ISO 8601 UTC start time of the at-bat
  "home_score": 0,                  // cumulative score after this play
  "away_score": 2,
  "description": "Jose Ramirez homers (34) on a fly ball to left field. …"
}

// Game-end marker (only present when game status is "Final")
{
  "event_type": "game-end"
}
```

Events are sorted by `(inning, half_inning, at_bat_index)`.
`event_type` is free text from the MLB Stats API (values include `"Home Run"`, `"Single"`, `"Walk"`, `"Sac Fly"`, `"Wild Pitch"`, etc.).
The `timestamp` field is the at-bat start time, **not** when the run scored.

### 3c. NBA Events

Only made field goals and free throws are captured — misses, turnovers, and fouls are omitted.

```jsonc
{
  "event_type": "2pt",              // "2pt" | "3pt" | "freethrow"
  "period": 2,                      // quarter number (1–4; 5+ for OT)
  "clock": "PT05M42.00S",           // ISO 8601 duration — time remaining in period
  "time_actual": "2025-10-16T01:07:53Z",  // wall-clock UTC timestamp of the action
  "home_score": 31,                 // cumulative score after this basket
  "away_score": 28,
  "team_tricode": "BOS",            // scoring team's 3-letter code
  "description": "Tatum 25' 3PT Jump Shot (7 PTS) (Brown 4 AST)"
}
```

Events are sorted by `actionNumber` (internal sequence from NBA CDN).
NBA events use `time_actual` (real UTC wall-clock time), unlike NHL/MLB which use game-relative time.
`clock` is ISO 8601 duration with millisecond precision — parse with `isodate` or manually: `PT05M42.00S` = 5 min 42 sec remaining.

---

## 4. Data Limitations & Gotchas

### Global

| Limitation | Details |
|---|---|
| **No in-progress games** | `is_final: false` entries in the manifest were not collected; play-by-play and final scores unavailable |
| **Polymarket coverage gaps** | Not all games have Polymarket markets; `polymarket_matched: false` entries have no trade data |
| **Trade timestamp is on-chain** | Timestamps reflect blockchain confirmation time, not the moment an order was placed |
| **Price != probability** | Prices approximate market-implied probability but are driven by liquidity and can be noisy for illiquid markets |

### Source-Specific

| Limitation | Details |
|---|---|
| **Data API trade cap** | `source: "data_api"` files are capped at ~4000 trades in live API behavior. High-volume games may be missing early trade history, and this appears to be an upstream server limit rather than a downloader bug |
| **Opening odds source varies** | `opening_odds` is derived from `price_checkpoints` — it uses CLOB data when available (~10% of games), otherwise the first pregame or first trade price. Check `price_checkpoints_meta.price_quality` to distinguish `"exact"` (CLOB) from `"inferred"` (trade-derived) |
| **Token order not guaranteed by spec** | `outcomes[0]` matches `token_ids[0]` (away team is typically index 0, but verify against `outcomes`) |

### Sport-Specific

| Sport | Limitation |
|---|---|
| **NBA** | Play-by-play CDN blocks cloud IPs with 403. Affected games have no events file on disk — detect via file existence, not `events_status` (not durable across re-scans) |
| **NBA** | `clock` field is ISO 8601 duration (time remaining), not elapsed — requires parsing |
| **NHL** | Shootout games: scores freeze in play-by-play at the tied value; use `scoring_team` on SO-period goals for winner |
| **NHL** | `match_id` uses event-specific slug overrides (e.g. Utah team uses `utah` not `uta`) — don't reconstruct slugs from team names |
| **MLB** | `event_type` is free-text from the Stats API — not a closed enum; normalize before grouping |
| **MLB** | `timestamp` is at-bat start time, not run-scored time — alignment with trade timestamps has ~2–5 min variance |
| **MLB** | Double-headers: game 2 `match_id` ends in `-g2`; always check `outcomes` to confirm team order |
| **MLB** | 2026 Spring Training begins on `2026-02-20`; MLB regular-season markets should not be expected again until `2026-03-25` / `2026-03-26`. Late-February MLB entries may remain `status: "scanned"` without indicating a pipeline failure |
| **Historical NBA** | `historical_*` match methods are Gamma-first. Most now carry official NBA `sports_api_id` and `_events.json` files, but some older entries lack league IDs — missing `_events.json` may reflect a mapping gap, not a collection failure |
| **Historical NBA** | Legacy match_id formats (`nba-play-in-*`, `nba-dailies-*`, `nba-finals-*`, `nba-preseason-*`) do not follow the standard `{sport}-{away}-{home}-{date}` pattern — do not parse team slugs or dates from these IDs |
| **NBA** | `2026-02-13` and `2026-02-15` may contain scanned All-Star / special-event entries (`Team Melo`, `Team Austin`, `Stars`, `World`, etc.) that remain unmatched. Treat them as non-standard schedule artifacts rather than missing regular-season markets |

---

## 5. Recommended Analysis Patterns

**Determining the winner from events:**
- NHL: find the last `goal` event → `home_score` vs `away_score`
- MLB: find the `game-end` marker → read `home_score`/`away_score` from the last scoring event before it
- NBA: last event → `home_score` vs `away_score`
- Cross-check against settlement price: winning token converges to ~1.0

**Building a price series:**
- Use all trades regardless of `side`
- Dedup by `transactionHash` if combining multiple files
- Both token prices should be plotted together (they sum to ~1.0)

**Excluding bad data:**
- Skip entries where `polymarket_matched: false` (no market data)
- Skip entries where `status != "collected"` (no trade file on disk)
- For event-trade alignment analysis, skip NBA games missing an events file — check file existence rather than `events_status` (that field is not durable across re-scans):
  ```python
  # Reliable: check file existence — events_status in manifest is not durable across re-scan
  has_events = (date_dir / f"{match_id}_events.json").exists()
  ```
- Be cautious with `source: "data_api"` files where `trade_count >= 3900` (likely truncated)
- Prefer running `poly-data-downloader rehydrate` on truncated fallback files before using them for opening-history analysis

---

**Identifying early / pre-game odds:**

Use `price_checkpoints` — it provides multiple price anchors per token with explicit provenance:

```python
import json

with open(f"{match_id}_trades.json") as f:
    trades_file = json.load(f)

cp = trades_file["price_checkpoints"]
meta = trades_file["price_checkpoints_meta"]

for tid in trades_file["token_ids"]:
    checkpoint = cp[tid]
    print(f"Token {tid}:")
    print(f"  CLOB open:            {checkpoint['clob_open']}")
    print(f"  First trade price:    {checkpoint['first_trade_price']}")
    print(f"  First pregame trade:  {checkpoint['first_pregame_trade_price']}")
    print(f"  Last pregame trade:   {checkpoint['last_pregame_trade_price']}")
    print(f"  Selected early price: {checkpoint['selected_early_price']}")
    print(f"  Source:               {checkpoint['selected_early_price_source']}")

print(f"Price quality: {meta['price_quality']}")
# "exact" = CLOB available, "inferred" = trade-derived, "unavailable" = no data
```

**Which field to use depends on your analysis:**

| Need | Use | Why |
|---|---|---|
| Market open price (earliest available) | `selected_early_price` | Best available across CLOB and trade sources |
| Price at game start (last pregame) | `last_pregame_trade_price` | Last traded price before `gamma_start_time` |
| VWAP near game start | Manual: filter trades before `gamma_start_time`, compute VWAP over last 15–30 min | More robust than a single price point for thin markets |
| Data quality gate | `price_checkpoints_meta.price_quality` | Filter to `"exact"` for CLOB-backed analysis |

**Caveats — read before using pre-game odds:**

| Caveat | Impact |
|---|---|
| `gamma_start_time` is scheduled, not actual | Polymarket's scheduled time can be 5–30 min off from actual start. For most analysis the difference is acceptable; for tight windows (< 5 min) it may matter |
| Trade density varies | Marquee games have many pre-game trades; small-market midweek games may have only a handful. Sparse pre-game windows make the last-price point noisy |
| CLOB history available for ~10% of games | Most games use trade-derived prices (`"inferred"` quality). For calibration analysis, consider filtering to `price_quality == "exact"` or flagging the source |
| Some markets opened days early | Compare `clob_open` (earliest CLOB point) to `last_pregame_trade_price` to see how much the market moved during the pre-game period |
| `history_truncated: true` files may have no pre-game trades | Fallback files capped by the Data API may be missing the oldest trades entirely. Run `rehydrate` on these before using them for pre-game analysis |
