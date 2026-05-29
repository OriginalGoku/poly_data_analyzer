# Tip-off Bucket + Max Favorite Price Filters

## Goal

Add two filters to the main Dash dashboard (`/`) so the user can narrow the game picker by:

1. **Tip-off Bucket** — bin games by the favorite-side price at tip-off, mirroring the existing "Open Bucket" filter.
2. **Max in-game anchor-side price** — exclude games where the team that was favorite at the *selected anchor* (open or tip-off) reached ≥ a configurable threshold (default 97%) at any point during the in-game window. Settlement irrelevant.

## UI

Replace the existing single "Open Bucket" dropdown in `pages/main_dashboard_page.py` (lines 100-113) with three controls in the filter row:

| Control | Type | Default | Notes |
|---|---|---|---|
| **Bucket Anchor** | Dropdown | `Open` | Options: `Open` \| `Tip-off`. |
| **Bucket** | Dropdown | `All` | Options: `All` + `ACTIVE_INTERPRETABLE_BAND_LABELS`. Identical to current "Open Bucket" options. |
| **Threshold filter** | Checkbox + numeric input | unchecked, value `0.97` | Default value from `chart_settings.json:max_favorite_price_threshold`. Numeric input bounded `[0.5, 1.0]`, step `0.01`. |

UI rules:

- Threshold filter activates iff checkbox = on. **Decoupled from bucket selection** — works at `bucket="all"` too because the anchor side is always known once Anchor is selected.
- When Anchor = `Tip-off`: rows with `tipoff_available == False` are excluded from the picker entirely (no warning badge for them in this filter; existing truncated-data badge unchanged elsewhere).
- Bucket dropdown labels do not change based on Anchor; both anchors use the same interpretable band labels.

## Filter callback semantics

In `pages/main_dashboard_page.py` callbacks (currently filtering on `open_interpretable_band` at lines 226, 259, 320, 353):

```python
if anchor == "open":
    band_col = "open_interpretable_band"
    fav_team_col = "open_favorite_team"
elif anchor == "tipoff":
    band_col = "tipoff_interpretable_band"
    fav_team_col = "tipoff_favorite_team"
    analytics = analytics[analytics["tipoff_available"] == True]

if bucket != "all":
    analytics = analytics[analytics[band_col] == bucket]

if threshold_enabled:
    away_max = analytics["away_in_game_max_price"]
    home_max = analytics["home_in_game_max_price"]
    fav_max = np.where(
        analytics[fav_team_col] == analytics["away_team"], away_max, home_max
    )
    analytics = analytics[(fav_max < threshold) | analytics[fav_team_col].isna()]
```

(Rows missing the extremes columns — i.e. NaN — are kept; threshold filter is only a hard exclusion when data is present and over the bar.)

## Precomputed per-team extremes (sidecar)

Per-game JSON sidecar:

- **Path:** `cache/<date>/<match_id>_ingame_extremes.json`
- **Schema version:** `1`

```json
{
  "schema_version": 1,
  "input_fingerprint": {
    "trades_path": "...",
    "trades_mtime": 1234567890.0,
    "trades_size": 12345,
    "events_mtime": ...,
    "events_size": ...,
    "manifest_mtime": ...,
    "manifest_size": ...
  },
  "away_team": "DET",
  "home_team": "BOS",
  "away_in_game_min_price": 0.21,
  "away_in_game_max_price": 0.44,
  "home_in_game_min_price": 0.56,
  "home_in_game_max_price": 0.79,
  "tipoff_source": "score_events",
  "window_quality": "high",
  "ingame_window_start": "2026-04-10T19:32:11Z",
  "ingame_window_end":   "2026-04-10T22:05:48Z"
}
```

### Settings-independence (resolves brainstorm critical issue #2)

The sidecar uses an **over-broad, settings-independent window** so changes to `post_game_buffer_min` do not silently stale the cache:

- **Window start:** earliest reliable tipoff anchor available for the sport (see "In-game window definition" below).
- **Window end:** `min(last_trade_timestamp, gamma_closed_time)` — never tied to `post_game_buffer_min`.

`post_game_buffer_min` is **not used** in the sidecar window. It remains a chart-time setting; if a future feature wants buffer-aware extremes, it must derive them at read time from a richer cached structure (out of scope here).

### In-game window definition (resolves brainstorm critical issue #3)

Per game:

| Sport / situation | Window start | Window end | `tipoff_source` | `window_quality` |
|---|---|---|---|---|
| Reliable score events present (NBA) | `min(event.time_actual_dt)` | `min(max(event.time_actual_dt), gamma_closed_time, last_trade_ts)` | `"score_events"` | `"high"` |
| No reliable score events + `gamma_closed_time` present (most NHL/MLB) | `gamma_start_time` | `min(gamma_closed_time, last_trade_ts)` | `"gamma_fallback"` | `"medium"` |
| No reliable score events AND `gamma_closed_time` missing | `gamma_start_time` | `last_trade_ts` | `"gamma_fallback_uncapped"` | `"low"` |
| No `gamma_start_time` at all | — | — | `"unavailable"` | `"none"` (all extremes `null`) |

`gamma_closed_time` is already exposed by `loaders.py:106-125` and documented in `DATA_SPEC.md:60`. Capping at it prevents post-settlement noise from inflating the in-game max.

### Idempotency contract (resolves brainstorm medium issue #2)

`input_fingerprint` is **persisted inside the sidecar payload**. Backfill re-runs:

1. Read sidecar if present.
2. Compare persisted `input_fingerprint` against current fingerprint of `(trades.json.gz, events.json, manifest.json)` mtime+size.
3. Match → skip without scanning the trade file.
4. Mismatch or missing → recompute, write.

## Backfill script

`scripts/backfill_ingame_extremes.py`:

- Iterate `data/<YYYY-MM-DD>/` directories.
- For each match: check sidecar idempotency; if rebuild needed, read `trades.json.gz` once (no double read), compute per-team extremes over the defined window, write sidecar atomically (tmp + rename).
- CLI flags: `--data-dir`, `--start-date`, `--end-date`, `--force` (ignore fingerprint match), `--dry-run`.
- Stdout phase timers (match the existing `[nba_tipoff]` convention from CLAUDE.md): `[ingame_extremes] scanned=… written=… skipped=… elapsed=…s`.

## Online compute (no backfill required)

Extend `analytics.stream_game_analytics()` so that for each game, if the sidecar is missing or fingerprint-stale, compute extremes on the fly from the already-loaded trades data and write the sidecar before yielding the base record. This keeps the dashboard usable without pre-running the backfill, at the cost of first-time-per-game latency. Subsequent loads are O(1).

## Base records projection

In `analytics.py:_collect_base_record(...)` (around line 498), project four fields from the sidecar into each base record:

- `away_in_game_min_price`
- `away_in_game_max_price`
- `home_in_game_min_price`
- `home_in_game_max_price`

Plus `away_team` / `home_team` if not already present (they are, via manifest `outcomes`).

### Base-records cache invalidation (resolves brainstorm critical issue #1)

Bump `BASE_RECORDS_CACHE_SCHEMA_VERSION` from `1` to `2` at `analytics.py:16`. Existing `cache/_base_records/*.pkl` files are invalidated by the version mismatch and will be regenerated on next load (one-time cost; standard pattern).

The new columns are **not** included in `_base_records_settings_hash` since they are settings-independent (the schema bump alone handles forward compatibility; future settings-independent additions can rely on the column-presence check below).

**Defensive column-presence check:** also add a check in `_load_base_records_cache` that drops the pickle if any expected column is missing — this protects against future additive fields that forget to bump the version.

## chart_settings.json

Add one key:

```json
"max_favorite_price_threshold": 0.97
```

`post_game_buffer_min`, `pregame_min_cum_vol`, etc. unchanged.

## Out of scope

- Changes to the legacy backtest framework (slated for removal in Step 19 per CLAUDE.md).
- Changes to the NBA tipoff page or its existing `open_favorite_in_game_max_price` computation in `nba_analysis.py:920-1009`. That code remains the source of NBA tipoff-page metrics; the new sidecar is a parallel, sport-agnostic, per-team artifact.
- Modifying `manifest.json` (upstream-owned by `poly-data-downloader` per `DATA_SPEC.md`).
- Per-team time-to-min / time-to-max / MAE / MFE — only the four min/max scalars are persisted. Future extensions can add timestamps without breaking the schema (bump `schema_version` to `2`).
- UI: collapsing empty bucket options per sport. Picker shows the full ACTIVE band list regardless of which sport has games.

## Files touched

- `pages/main_dashboard_page.py` — UI restructure + callback semantics
- `analytics.py` — schema-version bump, base-records projection, `stream_game_analytics` sidecar integration, defensive column check in `_load_base_records_cache`
- `chart_settings.json` — add `max_favorite_price_threshold`
- New: `ingame_extremes.py` — pure compute (`compute_ingame_extremes(manifest, events, trades_df) -> dict`) + `load_or_compute_ingame_extremes(...)` mirroring `nba_tipoff_cache.py` shape
- New: `scripts/backfill_ingame_extremes.py`
- New: `tests/test_ingame_extremes.py` — unit tests for window-definition table, idempotency, cache miss/hit, NaN handling for `tipoff_available=False`

## Open questions for /technical-plan

- Should `load_or_compute_ingame_extremes` live as a module sibling to `nba_tipoff_cache.py` (consistent) or be folded into `analytics.py`?
- Sidecar write contention: backfill and live `stream_game_analytics` could race on first-touch. Atomic tmp+rename is sufficient; confirm no read-during-write hazard for Dash callbacks.
- Concrete name for the threshold checkbox in the UI (e.g. "Cap reached games" toggle label) — cosmetic, defer to implementation.
