# Brainstorm — NBA Tipoff Page Performance Plan

Subject: `plans/NBA_Tipoff_Page_Performance_Plan/technical-plan.md`

## Critical issues found

1. **Step 2's optimization misses the page's actual code path.** `pages/nba_open_tipoff_page.py:217` calls `prepare_dataset` without a `progress_observer`. `nba_analysis.py:688-689` then takes the `get_analytics_view` branch, which routes through `_load_game_analytics_cached` and discards `trades_df`. The plan's `build_game_analytics_dataset_with_loaded_games` only helps the observer branch (progress UI / CLI). Cold goal ("roughly halved") is **unmet** on the page's real path. [grounded]
   - **Fix:** route the no-observer branch in `_build_nba_analysis_dataset` through a single bulk pass that produces base records + detail rows together, rather than splitting `get_analytics_view` + per-row `_load_nba_detail_row(load_game)`.

2. **Retain-all-games dict is a multi-GB memory blow-up.** Local 2026-01-01→04-10 NBA range: 719 trade files, ~826 MB compressed, ~10 MB parsed `trades_df` per game ⇒ ~7.4 GB resident if all retained. Plus events, manifest, base rows. Will OOM under typical dev RAM. [grounded]
   - **Fix:** Stream — don't retain. Make the helper yield (or invoke a callback for) `(base_record, loaded_game)` pairs; compute and persist the detail row immediately, then drop the game. Quantile bands attach later, after all base records are assembled (detail metrics don't depend on bands). This delivers Step 2's wins on the no-observer path **and** caps memory at one game at a time.

3. **Cache fingerprint missing `events_mtime`.** `_load_nba_detail_row` consumes `game["events"]` for tipoff time, end time, final winner, and pregame path metrics. The plan's `settings_hash` covers settings only; adding `trades_mtime`/`manifest_mtime` still omits events. If `<match_id>_events.json.gz` is re-collected or corrected, stale rows survive. [grounded]
   - **Fix:** add an explicit `input_fingerprint` field (separate from `settings_hash`) covering `(trades_mtime, manifest_mtime, events_mtime_or_none)`. Mismatch ⇒ recompute.

4. **Step 4 ordering must be explicit.** Date filter must run on `view` **before** `quantile_source = view` (analytics.py:73), not just "after the sport filter". Otherwise quantile bands silently become all-history-relative instead of date-range-relative. [grounded]
   - **Fix:** update Step 4 text to specify the exact insertion point (between line 71 sport filter and line 73 `quantile_source` assignment). Add a regression test with two dates whose prices differ enough that global vs window-local quantile bands diverge.

## Medium issues

- **Warm cache still requires gunzipping all trades to rebuild base records after a Dash restart.** The per-game detail disk cache only short-circuits the detail loop. To hit the ≤30s warm target across process restarts, persist the assembled base-records frame too (keyed by `(data_dir, settings, base_records_input_fingerprint)`). Otherwise warm-across-restart is bound by `build_game_analytics_dataset` reading every `trades.json.gz` for base records. [inferred]
- **Quantile-band semantics with `price_quality_filter="all"`.** Today's no-observer page path effectively uses `price_quality="all"` → quantile population is the full date-window unfiltered. Step 5 keeps price-quality as an `Input`; confirm the intended semantic (date-window relative, price-quality global) is preserved through the refactor. [grounded]
- **Step 5 option (A) preferred but plan doesn't specify the chosen Dash mechanism.** "Hidden dcc.Store populated at layout time" vs `Input("...-start-date", "id")` are different patterns. Pick one and verify with a manual test that toggling price-quality fires `update_analysis` exactly once. [grounded]

## Deferred issues

- `get_analytics_view`'s `view.apply(..., axis=1)` for band assignment (analytics.py:84-89) is O(n) per call; vectorize later.
- `sensitivity.py` / `dip_recovery.py` carry the same "settings-only cache key" weakness — out of scope here but worth a tracking note.

## What's solid

- Step 1 phase timers (`print(flush=True)` matches repo idiom).
- Step 3 cache module shape mirroring `sensitivity.py:114-139` is the right convention.
- Step 5 root-cause analysis on `populate_dates` retrigger.
- Step 6 test mirroring of `tests/test_sensitivity.py` is the right shape.
- Wave plan and critical path (1 → 2 → 3 → 6) are coherent.

## Open tradeoffs

- **Streaming helper vs preserving `get_analytics_view`'s lru_cache hit.** Streaming bypasses `_load_game_analytics_cached` on the page's cold path, sacrificing the in-process lru_cache hit that the second page load currently benefits from. Step 3 + persistent base-records cache (medium #1) compensate — and the lru_cache hit is only valuable within a single Dash process anyway. Recommended: accept the trade.
- **Strictness of input fingerprint.** `sensitivity.py` / `dip_recovery.py` rely on the implicit "raw data is immutable once collected" contract. If you trust it, settings_hash-only is fine. If not, `input_fingerprint` adds one `os.stat` per game (cheap). Recommended: add it; cost is negligible, correctness improves.

## Recommended next step

Update the plan to: (a) replace Step 2's "preserved old wrapper, observer-only optimization" with a streaming `_build_nba_analysis_dataset` that produces `(base_record, loaded_game)` pairs and writes detail cache per game; (b) add an `input_fingerprint` field to Step 3's cache payload covering manifest/trades/events mtimes; (c) tighten Step 4 wording to pin date filter before `quantile_source` assignment and add the divergent-quantile regression test; (d) add a Step 7 (persistent base-records cache) if the ≤30s warm-across-restart target matters.

---

## Source-Fix Alternatives (auxiliary)

Step 1 — Architectural assumptions:
- I assume the application runs as a Dash app via `app.py` on localhost:8050, processing NBA game data from ~99 date directories.
- I assume `analytics.py` contains `build_game_analytics_dataset` which invokes `_read_trade_data`, and `nba_analysis.py` contains `_load_nna_detail_row` which invokes `loaders.load_game`.
- I assume the double-read of `trades.json.gz` occurs because both `_read_trade_data` and `loaders.load_game` independently load the file during a cold run.
- I assume `populate_dates` is triggered by changes to the "price-quality dropdown" and resets the date range, causing a re-execution of the heavy callback.
- Unknown from problem statement: the internal implementation details of `loaders.load_game` (specifically whether it directly reads `trades.json.gz` or calls another helper).
- Unknown from problem statement: the specific structure of the cache key used by `lru_cache` beyond "settings_hash" and the dropped date.
- Unknown from problem statement: whether `nba_tipoff_cache.py` is part of the existing codebase or a new module being introduced as part of this change.

Step 2 — Upstream alternatives:
- If the system allows passing parsed data between modules, then upstream fix is to refactor `analytics.build_game_analytics_dataset` to return parsed trade data and modify `nba_analysis._load_nna_detail_row` to accept this data instead of calling `loaders.load_game`.
- If the system supports cross-module state sharing, then upstream fix is to modify `loaders.load_game` to check a shared cache for the parsed trade data before reading `trades.json.gz`.
- If the system allows consolidating parsing logic, then upstream fix is to move `_read_trade_data` into `loaders.py` and have both `analytics.build_game_analytics_dataset` and `nba_analysis._load_nna_detail_row` call this consolidated function.

## Pre-Mortem (auxiliary)

BASELINE: The `/nba-open-tipoff-analysis` Dash app currently requires ~5 minutes to process ~99 date directories containing 500–1000 games. Each cold run deserializes `trades.json.gz` twice per game because both `_read_trade_data` and `loaders.load_game` independently invoke the file. Cache behavior relies exclusively on `lru_cache`, meaning every Dash restart forces a full cold load without persistence. These redundant I/O operations and state resets compound into the observed multi-minute delay.

ROOT-CAUSE: The 5-minute latency stems from redundant I/O operations and a brittle UI state reset. Specifically, `trades.json.gz` is deserialized twice per game due to parallel calls in `_read_trade_data` and `loaders.load_game`, while the `populate_dates` callback silently resets the date range whenever the price-quality dropdown changes. Without persistent caching beyond `lru_cache`, these redundant reads and UI-triggered re-runs compound into the observed multi-minute delay.

SOURCE-FIX: The problem statement specifies removing the double-read to halve cold-run time, but completely omits how `analytics.build_game_analytics_dataset` and `nba_analysis._load_nba_detail_row` will coordinate to share trade data. Unknown from problem statement: how `populate_dates` will be decoupled from the price-quality dropdown without breaking the existing mount-time trigger, or how cache invalidation will transition beyond `settings_hash` to prevent silent re-triggers. There is no documented upstream mechanism that prevents the problem entirely, leaving both I/O duplication and state resets unaddressed.

SUCCESS-CRITERIA: Success requires measurable reduction in execution time and stable UI state across interactions. Specifically, cold-run latency must drop to roughly half the current ~5 minutes (≤2.5 minutes), and warm-load latency must consistently hit ≤1–2 minutes as stated in the goal. We will verify this by timing `app.py` startup cycles and confirming that switching the price-quality dropdown no longer resets the date range or re-triggers `analytics.build_game_analytics_dataset`. Unknown from problem statement: whether these time thresholds apply per-game or across the full 99-directory batch, and which monitoring logs will capture the `trades.json.gz` read counts.

FAILURE-MODE: The most probable silent failure is that modifying `populate_dates` or deduplicating `_read_trade_data` breaks the existing mount-time trigger, causing stale cache hits to serve outdated `trades.json.gz` data without raising errors. Because cache invalidation currently relies solely on `settings_hash`, any upstream change to the key generation logic could silently bypass cache misses, leading to incorrect quantile bands or regime summaries in `analytics.py`. Without explicit validation hooks, regressions in data accuracy will likely go undetected until downstream reports show discrepancies.
