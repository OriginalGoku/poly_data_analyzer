## Lens status

- **Probe:** completed (this session) — found double-read of trades.json.gz, in-memory-only caches, date-keyed base cache, callback re-trigger via `populate_dates`.
- **Brainstorm:** completed — surfaced 4 critical issues (Step 2 misses page path, ~7GB memory blow-up if games retained in dict, missing `events_mtime` fingerprint, Step 4 ordering ambiguity). Plan revised: Step 2 reshaped as streaming helper; Step 3 adds `input_fingerprint`; Step 4 wording tightened; new Step 7 (persistent base-records cache) added.
- **Review:** not run.

## Problem Statement

`/nba-open-tipoff-analysis` takes ~5 minutes for ~99 date dirs (Jan 1 – Apr 10 2026, ~500–1000 NBA games). Caches are `lru_cache` only (cold on every Dash restart), each game's `trades.json.gz` is loaded twice per cold run (once in `analytics.build_game_analytics_dataset` via `_read_trade_data`, again in `nba_analysis._load_nba_detail_row` via `loaders.load_game`), and changing the price-quality dropdown silently retriggers the heavy callback because `populate_dates` resets the date range. Goal: warm-load latency ≤1–2 minutes; first-cold-run roughly halved by removing the double-read.

## Codebase Context

- `pages/nba_open_tipoff_page.py:201-280` — `update_analysis` callback fires on price-quality / start / end / group-by; calls `prepare_dataset` → figures → table.
- `pages/nba_open_tipoff_page.py:188-199` — `populate_dates` callback depends on `nba-analysis-price-quality`; **always resets** start/end to a 30-day default → re-triggers `update_analysis`.
- `nba_analysis.py:641-662` — `_load_nba_analysis_dataset` `lru_cache(maxsize=8)`, key includes `start_date`/`end_date`.
- `nba_analysis.py:665-790` — `_build_nba_analysis_dataset`: calls `get_analytics_view` (no observer) or `build_game_analytics_dataset` (with observer); then loops `_load_nba_detail_row` per game.
- `nba_analysis.py:814-850` — `_load_nba_detail_row` `lru_cache(maxsize=256)`; calls `loaders.load_game(data_dir, date, match_id)` — full re-read of `trades.json.gz`.
- `analytics.py:113-130` — `_load_game_analytics_cached` `lru_cache(maxsize=4)`, key includes `start_date`/`end_date`.
- `analytics.py:133-202` — `build_game_analytics_dataset` reads each `trades.json.gz` via `_read_trade_data` (`analytics.py:223-226`).
- `loaders.py:56-121` — `load_game` reads `manifest.json` + `<match_id>_trades.json.gz` + optional events; produces `trades_df` with parsed datetime/team columns.
- Existing on-disk per-game cache idiom: `sensitivity.py:114-139` and `dip_recovery.py:97-121` — `cache_path = Path(cache_dir) / date / f"{match_id}_<kind>.json"`, `schema_version` constant, `load_or_compute_<kind>(...)`. Tests in `tests/test_sensitivity.py:186-220`.

### Reusable-Code Survey

- **`sensitivity.load_or_compute_sensitivity`** (`sensitivity.py:114-139`) — direct template for the new tipoff per-game cache function; same `cache_dir / date / match_id` shape, same `schema_version` guard.
- **`dip_recovery.load_or_compute_dip_recovery`** (`dip_recovery.py:97-121`) — second instance of the same idiom; confirms convention.
- **`loaders.load_game`** (`loaders.py:56-121`) — single-source loader; refactor target so detail loop can consume the already-loaded `game` dict instead of re-reading.
- Searched: `sensitivity.py`, `dip_recovery.py`, `regime_transitions.py`, `discrepancy.py`, `loaders.py`, `analytics.py`, `nba_analysis.py`, `wiki/decisions-log.md`. No graphify output (`graphify-out/` absent).

## Pre-Change Baseline

- **Wallclock (cold, Dash restart, Jan 1 – Apr 10 2026, NBA, all price quality):** ~5 minutes (user-reported).
- **Wallclock (warm, same range, same Python process):** unmeasured (lru_cache hit; expected sub-second once `_load_nba_analysis_dataset` cache key matches).
- **Trades.json.gz disk reads per cold game:** 2 (one in `analytics._read_trade_data`, one in `loaders.load_game` via `_load_nba_detail_row`).
- **Persistent on-disk cache for tipoff dataset:** none.
- **`populate_dates` retrigger:** changing price-quality dropdown resets start/end and silently re-runs `update_analysis`.
- **Instrumentation in callback / pipeline:** none.

## Verification Signal

- `print()`/`logging` lines emitted from each phase make the wait observable in the Dash terminal.
- Cold run for Jan 1 – Apr 10 2026 reports ≥40% wallclock reduction after Step 2 (double-read removed), measured via the Step 1 timers.
- Warm run after first cold completion (cache hit on disk) for the same range completes in ≤30 seconds.
- Changing only the price-quality dropdown does **not** reset start/end values and does **not** retrigger `update_analysis` end-to-end (verified by terminal timers showing zero or one heavy call, not two).
- New tests in `tests/test_nba_tipoff_cache.py` pass: cache miss writes the file, cache hit returns identical rows without recomputation.
- Existing tests (`tests/test_nba_analysis.py`, `tests/test_sensitivity.py`, `tests/test_dip_regime.py`) still pass.

## Implementation Steps

### Step 1: Add phase timers to the tipoff pipeline
Files: nba_analysis.py
Depends on: none

**What changes:**
- Wrap the three phases of `_build_nba_analysis_dataset` with `time.perf_counter()`: (a) base-record build (`get_analytics_view` / `build_game_analytics_dataset`), (b) detail-row loop, (c) post-processing into `pd.DataFrame`.
- Emit one log line per phase with elapsed seconds and game count, e.g. `[nba_tipoff] base_records=523 elapsed=42.1s`.
- Use `print(..., flush=True)` (matches existing repo style — no logger configured) so output appears in the Dash terminal.

**Test strategy:**
- Manual: load `/nba-open-tipoff-analysis` for a 7-day range, confirm three phase lines appear in terminal with non-zero seconds.

### Step 2: Eliminate double-read of trades.json.gz via streaming helper
Files: nba_analysis.py, analytics.py
Depends on: Step 1

**Why streaming (not retain-in-dict):** retaining ~1000 decompressed games in a dict is ~7.4 GB resident (719 NBA files × ~10 MB parsed `trades_df` each, before events/manifests). Memory blow-up risk under typical dev RAM. Streaming caps RAM at one game at a time and delivers the same I/O win.

**Critical fix:** the page calls `prepare_dataset` **without** a `progress_observer` (`pages/nba_open_tipoff_page.py:217`), so `_build_nba_analysis_dataset` takes the `get_analytics_view` branch (`nba_analysis.py:688-689`) which discards `trades_df` through `_load_game_analytics_cached`. The naive "retain only in observer branch" design misses the page's actual cold path entirely. Both branches must use the streaming helper.

**What changes:**
- Add `stream_game_analytics(...)` in `analytics.py` that yields `(base_record, loaded_game)` tuples one at a time. Same scan logic as `build_game_analytics_dataset` but emits per-game instead of accumulating + returning `pd.DataFrame`. `loaded_game` matches `loaders.load_game`'s return shape (so detail code is unchanged).
- Refactor `_load_nba_detail_row` to a new `_compute_nba_detail_row_from_game(game, settings, open_favorite_team, open_favorite_price) -> dict`.
- Rewrite `_build_nba_analysis_dataset` to iterate `stream_game_analytics(...)`, computing each detail row immediately (or via the disk cache from Step 3) and dropping the game before the next iteration. Then assemble base records, attach quantile bands (same logic as `get_analytics_view:73-89`), and produce the final frame. Apply to **both** observer and no-observer branches.
- Keep `_load_nba_detail_row` lru_cache wrapper alive as a thin wrapper that calls `load_game` then `_compute_nba_detail_row_from_game` (preserves the lru_cache layer for non-bulk callers and existing tests).
- Keep `build_game_analytics_dataset` and `get_analytics_view` as public APIs for non-tipoff callers (`discrepancy.py`, `regime_transitions.py`, etc.); they're unchanged.

**Semantic-preservation requirement:** the new no-observer path must reapply quantile bands using the **date-filtered** view as the quantile population (matching today's `get_analytics_view` semantics — see Step 4). Do not compute bands from the full repo-wide records.

**Test strategy:**
- Manual: rerun the 7-day range from Step 1 and confirm the detail-loop phase drops materially (no second gunzip per game) and RSS stays flat (`ps -o rss=` on the Dash process before vs. mid-load).
- Existing `tests/test_nba_analysis.py` must still pass unchanged.
- Add a regression test: synthetic 3-game fixture where global vs. date-window quantile bands diverge, asserting the no-observer path produces the date-window bands.

### Step 3: Persistent per-game disk cache for tipoff detail rows
Files: nba_tipoff_cache.py, nba_analysis.py
Depends on: Step 2

**What changes:**
- New module `nba_tipoff_cache.py` mirroring `sensitivity.py:114-139`:
  - `NBA_TIPOFF_CACHE_SCHEMA_VERSION = 1`
  - `load_or_compute_nba_tipoff_detail(cache_dir, date, match_id, game, settings, open_favorite_team, open_favorite_price) -> dict`
  - Cache path: `Path(cache_dir) / date / f"{match_id}_nba_tipoff.json"`
  - Payload: `{"schema_version": 1, "settings_hash": "<sha1>", "input_fingerprint": "<sha1>", "row": {...}}`
  - On hit: validate `schema_version`, `settings_hash`, AND `input_fingerprint` all match; on any mismatch: compute via `_compute_nba_detail_row_from_game` (Step 2) and rewrite payload.
- `settings_hash`: stable hash over the tuple `(pregame_min_cum_vol, vol_spike_std, vol_spike_lookback, post_game_buffer_min, open_favorite_team, open_favorite_price)` — anything that affects the detail row's value.
- `input_fingerprint`: stable hash over `(trades_mtime_ns, trades_size, manifest_mtime_ns, manifest_size, events_mtime_ns_or_none, events_size_or_none)`. One `os.stat` per file (cheap). Catches re-collected/corrected raw data; `sensitivity.py` / `dip_recovery.py` skip this and rely on the implicit "raw data immutable" contract — we don't, because the tipoff page is the user-visible perf cache.
- In `_build_nba_analysis_dataset`, replace the direct call to `_compute_nba_detail_row_from_game` with `load_or_compute_nba_tipoff_detail(cache_dir, ...)` when `cache_dir` is configured. Default `cache_dir = "cache"` (matches `dip_recovery.py` / `sensitivity.py` callers).
- Plumb `cache_dir` through `NBAOpenTipoffAnalysisService.__init__` (default `"cache"`).
- Keep `_load_nba_detail_row` lru_cache wrapper working as a fallback for tests/non-cache callers.

**Test strategy:**
- Manual: cold-load Jan 1 – Apr 10 2026 once; confirm `cache/<date>/<match_id>_nba_tipoff.json` files appear; reload same range; confirm phase timer for detail-loop drops to single-digit seconds.
- Cache invalidation: bump `pregame_min_cum_vol` in settings, reload, confirm cache misses (new files written).

### Step 4: Drop date-range from base analytics cache key
Files: analytics.py
Depends on: none

**What changes:**
- Change `_load_game_analytics_cached` key to drop `start_date` / `end_date`. Build the full repo-wide records once; filter by date in the caller `get_analytics_view`.
- **Exact insertion point (critical):** in `get_analytics_view` (`analytics.py:69-89`), the date filter must run on `view` **between** the sport filter (line 71) and `quantile_source = view` (line 73). Applying it after line 73 silently switches quantile bands from date-window-relative to all-history-relative — a semantic regression.
- Bump `lru_cache(maxsize=4)` to `maxsize=2` (only one global frame per `(data_dir, settings)` matters now).
- `build_game_analytics_dataset` keeps its date-range parameters (the progress-observer path still wants narrow scans). Only the cached wrapper changes.

**Test strategy:**
- Existing `tests/test_nba_analysis.py` — re-run, must pass.
- **New regression test** in `tests/test_analytics.py`: build a synthetic 4-game fixture across 2 dates where global vs. window-local quantile bands differ (e.g., 2 games at price 0.6 on date A, 2 games at price 0.9 on date B; window = date A only). Assert bands match the window-local population, not the full set. Fails fast if the date-filter insertion drifts.
- Manual: load page for 30-day range, then immediately switch to 60-day range. Confirm Step 1 base-records timer reports 0.0s on the second load.

### Step 5: Stop `populate_dates` retriggering on price-quality change
Files: pages/nba_open_tipoff_page.py
Depends on: none

**What changes:**
- Decouple date population from `nba-analysis-price-quality`. **Picked: option A via hidden `dcc.Store`.** Add `dcc.Store(id="nba-analysis-init", data=0)` to the layout; `populate_dates` takes `Input("nba-analysis-init", "data")` as its sole trigger (fires once on mount). Remove `Input("nba-analysis-price-quality", ...)`.
  - Rejected: `Input("nba-analysis-start-date", "id")` mount-fire trick — works but reads as a hack; `dcc.Store` is the documented idiom.
  - Rejected: option B (compare-and-skip via `callback_context` + `State`) — still leaves a possibility of re-fire on any date change for any reason.
- Verify with terminal timers (Step 1) that toggling price-quality emits exactly one `update_analysis` invocation, not two.

**Test strategy:**
- Manual: load page, change price-quality dropdown 3 times, confirm timer block prints 3 times (not 6) and start/end values stay where the user left them.

### Step 6: Unit tests for the tipoff cache helper
Files: tests/test_nba_tipoff_cache.py
Depends on: Step 3

**What changes:**
- Mirror `tests/test_sensitivity.py:186-220` shape:
  - `test_cache_miss_writes_and_returns_row`
  - `test_cache_hit_skips_compute` (use a sentinel by stubbing `_compute_nba_detail_row_from_game` and asserting it is not called the second time)
  - `test_settings_hash_invalidates_on_change` (different `pregame_min_cum_vol` triggers recompute even with a cached file present)
  - `test_schema_version_mismatch_invalidates`
- Use `tmp_path` for `cache_dir`; minimal `game` dict and `ChartSettings` fixture.

**Test strategy:**
- `pytest tests/test_nba_tipoff_cache.py` green.
- Add `test_input_fingerprint_invalidates_on_trades_mtime_change` and `test_input_fingerprint_invalidates_on_events_mtime_change` (touch the file via `os.utime`, assert recompute).
- Full `pytest` suite still green.

### Step 7: Persistent base-records cache (cross-restart warm)
Files: analytics.py, nba_analysis.py
Depends on: Step 2, Step 4

**Why:** Step 3 only caches the detail loop. After a Dash restart, the streaming helper still re-reads every `trades.json.gz` to rebuild base records — the cold path remains ~half the original 5min. To hit ≤30s warm-across-restart, the base-records frame itself must persist.

**What changes:**
- New on-disk cache for the assembled base-records DataFrame.
- Cache path: `cache/_base_records/<settings_hash>.parquet` (single file, not per-game; ~1000 rows × ~30 cols fits in <5 MB parquet).
- Sidecar manifest `<settings_hash>.manifest.json` records `{schema_version, input_fingerprint_map: {(date, match_id): "<sha>"}}` for staleness detection.
- `stream_game_analytics` (Step 2) checks the manifest before scanning: for each `(date, match_id)` whose `input_fingerprint` matches, yield the cached base record without reading `trades.json.gz`; for mismatches or new games, scan + compute + update both parquet and manifest atomically (write to `.tmp`, rename).
- `settings_hash` here covers `(pregame_min_cum_vol, open_anchor_stat, open_anchor_window_min)` — anything that changes base-record values.

**Test strategy:**
- Manual: cold-load full date range, restart Dash, reload — confirm Step 1's base-record phase timer drops from ~minutes to single-digit seconds.
- Add unit test in `tests/test_analytics.py`: write a base-records cache, touch one trade file's mtime, reload, assert only that one game was rescanned.

## Execution Preview

- **Wave 0** (parallel, 3 steps): Step 1 (timers), Step 4 (analytics cache key), Step 5 (page callback)
- **Wave 1** (1 step): Step 2 (streaming helper; depends on Step 1 to share `nba_analysis.py` edits cleanly)
- **Wave 2** (1 step): Step 3 (per-game disk cache; depends on Step 2's refactored detail function)
- **Wave 3** (1 step): Step 7 (base-records cache; depends on Step 2 + Step 4)
- **Wave 4** (1 step): Step 6 (tests; depends on Step 3)
- **Total waves:** 5 · **Max parallelism:** 3 · **Critical path:** Step 1 → 2 → 3 → 7 → 6

## Risk Flags

- **Cache-key correctness (Step 3):** `settings_hash` must include every `ChartSettings` field touched by `_compute_in_game_open_favorite_metrics` and `PregameFavoritePathAnalyzer` — cross-check against `nba_analysis.py:867-962` before shipping. `input_fingerprint` covers raw-data drift independently.
- **Wave-0 file overlap on `nba_analysis.py`:** Step 1 and Step 2 both touch it; Step 2 depends on Step 1 to avoid a parallel-edit collision.
- **Step 4 semantic preservation:** date filter MUST precede `quantile_source` assignment. Wrong ordering silently flips quantile bands to all-history-relative — the regression test in Step 4 catches this.
- **Step 4 first-cold scan-all:** dropping date from the cache key means the first cold load scans **all** date dirs even for a narrow range. One-time penalty per process; subsequent ranges are free. Step 7 makes this survive Dash restarts.
- **Step 2 quantile-band reapplication:** the streaming no-observer path must reapply bands using the date-filtered view as the quantile population (matching Step 4 semantics). Covered by the Step 2 regression test.
- **Step 7 parquet dependency:** `pyarrow` or `fastparquet` must be available. If not in `requirements.txt`, add it. Alternative: pickle (smaller dep footprint, less inspectable).
- **`get_analytics_view` recomputes quantiles per call:** Step 4 doesn't fix this; `view.apply(...)` per row is O(n). Out of scope; flag for a follow-up.
- **Parallelism deferred:** explicitly out of scope per user direction. If Step 2 + Step 3 + Step 7 fall short of the ≤30s warm target, reopen with a parallelism follow-up plan.

## Open Questions

- Parquet vs pickle for Step 7 base-records cache — parquet is more inspectable but adds a `pyarrow` dep. Default to parquet unless `requirements.txt` review says otherwise.
- Is the "raw data immutable once collected" contract documented anywhere strong enough that we could skip `events_mtime` in the input fingerprint? Currently assuming no — fingerprint includes it.

## Verification

1. Run `pytest` — full suite green, including new quantile-band regression test (Step 2 + Step 4) and `input_fingerprint` tests (Step 6).
2. Cold-restart Dash with no `cache/` dir, load `/nba-open-tipoff-analysis` for Jan 1 – Apr 10 2026, capture terminal phase timers; expect ≥40% reduction vs baseline ~5 min from removing the double-read alone.
3. Reload the same range WITHOUT restarting Dash; expect sub-second (lru_cache hit).
4. **Restart Dash** with `cache/` warm, reload same range; expect ≤30 s (Step 3 + Step 7 cross-restart warm path).
5. Toggle price-quality dropdown 3 times; expect 3 `update_analysis` invocations (not 6) and start/end values unchanged.
6. Inspect `cache/2026-03-02/nba-*_nba_tipoff.json` — confirm payload includes `schema_version`, `settings_hash`, AND `input_fingerprint`.
7. Inspect `cache/_base_records/<settings_hash>.parquet` and matching `.manifest.json` — confirm presence and that `input_fingerprint_map` covers every game.
8. Touch one `<match_id>_trades.json.gz` (`os.utime`), reload — confirm only that game's detail row AND base record are recomputed (others cache-hit).
9. Monitor RSS during cold load — confirm memory stays flat (streaming, no dict accumulation).
6. Bump `pregame_min_cum_vol` in `chart_settings.json`, reload — confirm cache invalidation (new files written, old payload superseded).

<!-- toolkit: check=clean waves=clean gate=clean -->
