## Lens status
- Quality: not run
- Security: not run
- Audit: not run

## Problem Statement

Main dashboard (`/`) currently bins games by a single "Open Bucket" filter on `open_interpretable_band`. Tip-off-anchored band data is already computed (`tipoff_interpretable_band` at `analytics.py:449`) but unexposed. No per-team in-game price extremes are persisted, so a "did the favorite ever cross 97%?" filter cannot be enforced without re-reading each `trades.json.gz` at query time.

Goal: add a Tip-off bucket filter (anchor-selectable) and a max anchor-side in-game price filter (default 97%, configurable), backed by a settings-independent per-game sidecar containing per-team in-game min/max prices, so filtering remains O(1) at query time and works across NBA/NHL/MLB. Decisions locked in `features/tip-off-bucket-and-max-favorite-price-filters/feature.md`.

## Codebase Context

- `analytics.py:16` — `BASE_RECORDS_CACHE_SCHEMA_VERSION = 1`; cache invalidated only on schema mismatch or input-fingerprint mismatch.
- `analytics.py:19-28` — `_base_records_settings_hash` covers `pregame_min_cum_vol`, `open_anchor_stat`, `open_anchor_window_min`. Settings-independent columns won't change the hash.
- `analytics.py:39-46` — `_base_records_input_fingerprint` already covers trades + manifest + events mtime/size; reusable shape for the sidecar.
- `analytics.py:91-102` — `INTERPRETABLE_BANDS` + `ACTIVE_INTERPRETABLE_BAND_LABELS` already drive the bucket dropdown labels.
- `analytics.py:377-417` — `stream_game_analytics` loop; warm-cache hit branch (lines 385-386) is where post-projection of sidecar columns must occur.
- `analytics.py:430-450` — `_compute_base_record` is the cold-path producer; sidecar projection added here.
- `analytics.py:447-449` — `tipoff_interpretable_band` already computed for every base record.
- `analytics.py:498-515` — `_build_game_record` is where `tipoff_available`, `away_team`, `home_team` are set.
- `loaders.py:80-126` — `build_loaded_game` returns `manifest`, `trades_df`, `events`, `gamma_start`, `gamma_closed`. `gamma_closed_time` parsed from manifest at line 106 — feeds the in-game window upper bound.
- `loaders.py:108-115` — events loaded from `<match_id>_events.json.gz`; each `time_actual` parsed into `time_actual_dt`. Source for score-event-derived tipoff/end.
- `nba_tipoff_cache.py:1-80` — canonical per-game sidecar pattern: `compute_input_fingerprint`, `_stable_hash`, `load_or_compute_*` with cache-path `cache/<date>/<match_id>_<kind>.json` and `{schema_version, settings_hash, input_fingerprint, row}` payload shape.
- `nba_analysis.py:920-1009` — existing single-team (open-favorite-only) in-game min/max compute. Reference algorithm; new module generalizes to per-team across all sports.
- `pages/main_dashboard_page.py:100-113` — single "Open Bucket" dropdown wired to `bucket-picker`.
- `pages/main_dashboard_page.py:226, 258-259, 320, 352-353` — bucket consumed in two callbacks (`populate_games`, `update_game`).
- `pages/main_dashboard_page.py:230-244` — `get_analytics_view` invocation; new columns project through unchanged.
- `chart_settings.json` — analyzer-config home; `post_game_buffer_min: 10` is the runtime buffer. New key `max_favorite_price_threshold` added here.
- `DATA_SPEC.md:60` — `gamma_closed_time` is upstream-documented; safe to use for window cap.

### Reusable-Code Survey

- **`nba_tipoff_cache.py:50-122`** — canonical sidecar shape (settings_hash + input_fingerprint, atomic tmp+rename, `load_or_compute_*` signature with lazy `game_provider`). New `ingame_extremes.py` follows this template verbatim, dropping `settings_hash` since extremes are settings-independent.
- **`analytics.py:39-46` `_base_records_input_fingerprint`** — same trades+manifest+events fingerprint shape needed by the new sidecar; the new module gets its own (since it doesn't depend on `data_dir` indirection) but mirrors the format.
- **`nba_analysis.py:951-1009` in-game window + per-team price-path logic** — algorithmic reference for `compute_ingame_extremes`. Adapted to per-team (away+home) min/max with gamma_closed_time cap instead of post_game_buffer_min.
- **`analytics.py:_assign_interpretable_band`** — bucket bin lookup; reused unchanged when the Tip-off dropdown swaps to `tipoff_interpretable_band`.
- Searched: `nba_tipoff_cache.py`, `nba_analysis.py`, `analytics.py`, `dip_recovery.py`, `sensitivity.py`, `discrepancy.py`, `regime_transitions.py`, `loaders.py`, `chart_settings.json`. `graphify-out/` not present.

## Pre-Change Baseline

- Filter: single "Open Bucket" dropdown only. No Tip-off bucket filter. No max in-game price filter.
- Sidecars present in `cache/<date>/`: `_sensitivity.json`, `_dip_recovery.json`, `_regime_transitions.json`, `_discrepancy.json`, `_nba_tipoff.json`. No `_ingame_extremes.json`.
- Base records frame columns: `date`, `match_id`, `sport`, `away_team`, `home_team`, `label`, `price_quality`, `open_favorite_team/price`, `open_price_source`, `tipoff_favorite_team/price`, `tipoff_available`, `in_game_notional_usdc`, `pre_game_notional_usdc`, `trade_count`, `open_interpretable_band`, `tipoff_interpretable_band`.
- `BASE_RECORDS_CACHE_SCHEMA_VERSION = 1`.
- `chart_settings.json` has 33 keys; `max_favorite_price_threshold` not present.
- Dashboard startup loads base records once; bucket filter is the only band-axis filter in either `populate_games` or `update_game`.

## Verification Signal

- `Tip-off` selected as Bucket Anchor + `Lower Strong` as Bucket → game picker lists only games whose `tipoff_interpretable_band == "Lower Strong"`; games with `tipoff_available=False` are absent.
- Threshold checkbox on + value `0.97`, anchor=Open, bucket=All → game picker excludes any game whose open-favorite-team `in_game_max_price >= 0.97`; NaN-extremes rows remain visible.
- Threshold checkbox off → game picker output identical to current behavior (modulo new bucket-anchor mechanics).
- Backfill script run twice on the same date range → second run reports `skipped == scanned` and writes zero new sidecars.
- After running backfill, deleting one sidecar, and restarting `python app.py` → dashboard load recomputes only that one game's extremes (`stream_game_analytics` writes the missing sidecar on the fly).
- Existing `cache/_base_records/*.pkl` files: one-time invalidation on first run after the schema bump (manifest `schema_version != 2` → pickle dropped, regenerated).
- `pytest tests/test_ingame_extremes.py` passes; existing `pytest` suite (`tests/test_analytics.py`, `tests/test_nba_tipoff_cache.py`) passes with no regressions.

## Implementation Steps

### Step 1: Add per-team in-game extremes module
Files: ingame_extremes.py
Depends on: none

**What changes:**
- New module `ingame_extremes.py` mirroring `nba_tipoff_cache.py` shape but settings-independent.
- Constant `INGAME_EXTREMES_SCHEMA_VERSION = 1`.
- `compute_input_fingerprint(data_dir, date, match_id) -> str` — reuses the trades+manifest+events mtime+size SHA1 (same shape as `nba_tipoff_cache.compute_input_fingerprint`).
- `compute_ingame_extremes(manifest, events, trades_df, gamma_start, gamma_closed) -> dict` — pure compute. Returns sidecar payload (no `schema_version` / `input_fingerprint` wrappers — caller adds them). Window logic per `feature.md` "In-game window definition" table:
  - reliable score events present → `min(time_actual_dt)` → `min(max(time_actual_dt), gamma_closed_time, last_trade_ts)`; `tipoff_source="score_events"`, `window_quality="high"`.
  - else if `gamma_closed_time` present → `gamma_start` → `min(gamma_closed_time, last_trade_ts)`; `"gamma_fallback"`, `"medium"`.
  - else if `gamma_start` present → `gamma_start` → `last_trade_ts`; `"gamma_fallback_uncapped"`, `"low"`.
  - else → all four extremes `None`, `tipoff_source="unavailable"`, `window_quality="none"`.
- Per-team extremes: project trades into per-team `price` series via `manifest["outcomes"]` / `manifest["token_ids"]` (away=`[0]`, home=`[1]` per CLAUDE.md), slice to window, compute `min`/`max` per team.
- `load_or_compute_ingame_extremes(cache_dir, data_dir, date, match_id, game_provider=None, game=None) -> dict` — cache-path `cache/<date>/<match_id>_ingame_extremes.json`. On hit (schema match + fingerprint match): return cached payload's `row`. On miss: invoke `game_provider()` or use `game`, call `compute_ingame_extremes`, write payload `{schema_version, input_fingerprint, row: <extremes>}` atomically (tmp + `os.replace`).
- No `settings_hash` field. Payload schema documented as feature.md §"Precomputed per-team extremes".

**Test strategy:**
- `tests/test_ingame_extremes.py`: unit tests for window-table cases (score_events / gamma_fallback / gamma_fallback_uncapped / unavailable). Synthetic manifest + events + trades_df.
- Per-team min/max correctness with both away-token-major and home-token-major trade ordering.
- `gamma_closed_time` cap excludes a post-close trade that would otherwise be the max.
- Cache hit returns persisted row without calling `game_provider` (use a counter callable).
- Cache miss triggers compute and writes sidecar JSON; fingerprint persisted matches `compute_input_fingerprint`.
- Fingerprint mismatch on stale sidecar triggers recompute; matching mtime+size triggers reuse.

### Step 2: Add threshold default to chart_settings.json
Files: chart_settings.json
Depends on: none

**What changes:**
- Insert one key: `"max_favorite_price_threshold": 0.97`.
- Place it alphabetically near `data_warning_min_pregame_vol` and `analysis_min_open_favorite_price`.

**Test strategy:**
- Manual: `python -c "import json; json.load(open('chart_settings.json'))"` to assert valid JSON.
- No new code consumes this key in Step 2; verification rolls into Steps 4-5 where the UI reads it.

### Step 3: Backfill script for existing per-date directories
Files: scripts/backfill_ingame_extremes.py
Depends on: Step 1

**What changes:**
- New script `scripts/backfill_ingame_extremes.py`. CLI: `--data-dir data` `--cache-dir cache` `--start-date YYYY-MM-DD` `--end-date YYYY-MM-DD` `--force` `--dry-run`.
- For each `data/<date>/` matching the range, iterate manifest entries with `status == "collected"` (mirroring `analytics.py:332-337`).
- For each (date, match_id): compute current fingerprint via `ingame_extremes.compute_input_fingerprint`. If sidecar exists and fingerprint matches and `--force` not set → skip. Else → call `loaders.build_loaded_game` (single trades read), call `ingame_extremes.compute_ingame_extremes`, write sidecar via `load_or_compute_ingame_extremes` semantics (or a thinner `write_sidecar` helper added to Step 1).
- Phase-timer stdout: `[ingame_extremes] scanned=… written=… skipped=… elapsed=…s` (matches `[nba_tipoff]` style noted in CLAUDE.md).
- `--dry-run` reports counts without writing.

**Test strategy:**
- `tests/test_backfill_ingame_extremes.py`: build temporary `data/<date>/` fixture with two collected manifests + minimal trades+events. Run script as a Python entry-point (`from scripts.backfill_ingame_extremes import main; main([...])`). Assert two sidecars written.
- Idempotency: second invocation → 0 written, 2 skipped.
- `--force` regenerates regardless of fingerprint.
- `--dry-run` writes nothing.

### Step 4: Project extremes into base records + bump cache schema version
Files: analytics.py
Depends on: Step 1

**What changes:**
- Bump `BASE_RECORDS_CACHE_SCHEMA_VERSION` from `1` to `2` at `analytics.py:16`. Existing pkls invalidated by the manifest schema-mismatch check at line 58.
- In `_compute_base_record` (analytics.py:430-450), after band assignment, call `ingame_extremes.load_or_compute_ingame_extremes(cache_dir_path, data_dir, date_name, match_id, game_provider=lambda: build_loaded_game(data_dir, date_name, manifest, trades_data))` — passing the already-loaded `trades_data` through avoids a second read. Project four scalars into the record: `away_in_game_min_price`, `away_in_game_max_price`, `home_in_game_min_price`, `home_in_game_max_price`.
- In `stream_game_analytics` warm-cache branch (analytics.py:385-386): warm-cache rows from the rebuilt pkl (schema v2) already contain the four columns. **Defensive column-presence check** in `_load_base_records_cache` (analytics.py:49-65): if any row in the loaded `records_by_key` is missing any of the four extreme keys, return `{}, {}` (force regeneration). Protects against future additive fields skipping the version bump.
- `_compute_base_record` signature extended to accept `cache_dir_path` and `data_dir` parameters so it can drive sidecar load/write; thread the values through `stream_game_analytics` call sites (both warm-miss branches at lines 388-396 and 400-409).
- Document in module docstring or inline comment: extremes columns are settings-independent — survive future settings-hash changes without recompute.

**Test strategy:**
- Extend `tests/test_analytics.py`: assert `_compute_base_record` produces the four extreme keys for a fixture game; assert values match `ingame_extremes.compute_ingame_extremes` for the same fixture.
- Schema bump: load a v1-manifest fixture with the new code → cache miss returned, regenerate writes v2.
- Column-presence check: pickle records missing `away_in_game_max_price` → `_load_base_records_cache` returns `{}, {}`.
- End-to-end: `stream_game_analytics` second run hits warm cache, returns records with extremes columns populated.

### Step 5: Replace bucket UI + filter callbacks
Files: pages/main_dashboard_page.py
Depends on: Step 2, Step 4

**What changes:**
- Layout (`pages/main_dashboard_page.py:98-113`): replace the single "Open Bucket" `html.Div` with three `html.Div` children:
  - "Bucket Anchor" dropdown id=`bucket-anchor-picker`, options `[{"label": "Open", "value": "open"}, {"label": "Tip-off", "value": "tipoff"}]`, default `"open"`, `clearable=False`.
  - "Bucket" dropdown id=`bucket-picker` (id preserved for minimal callback churn), options unchanged: `[{"label": "All", "value": "all"}] + [{"label": L, "value": L} for L in ACTIVE_INTERPRETABLE_BAND_LABELS]`, default `"all"`, `clearable=False`.
  - "Max anchor-side price" group: `dcc.Checklist` id=`threshold-enable` with single `{"label": "Cap reached games", "value": "on"}` option (off by default); adjacent `dcc.Input` id=`threshold-value`, `type="number"`, `min=0.5`, `max=1.0`, `step=0.01`, `value=settings_dict.get("max_favorite_price_threshold", 0.97)`.
- Callback `populate_games` (line 217-276): add `Input("bucket-anchor-picker", "value")`, `Input("threshold-enable", "value")`, `Input("threshold-value", "value")`. Replace bucket-filter block (line 258-259) with helper `_apply_bucket_and_threshold(analytics, anchor, bucket, threshold_on, threshold_value)`:
  - If `anchor == "tipoff"`: `analytics = analytics[analytics["tipoff_available"].fillna(False)]`.
  - `band_col = "tipoff_interpretable_band" if anchor == "tipoff" else "open_interpretable_band"`; `fav_team_col = "tipoff_favorite_team" if anchor == "tipoff" else "open_favorite_team"`.
  - If `bucket and bucket != "all"`: `analytics = analytics[analytics[band_col] == bucket]`.
  - If `threshold_on and threshold_value is not None`: compute `fav_max = np.where(analytics[fav_team_col] == analytics["away_team"], analytics["away_in_game_max_price"], analytics["home_in_game_max_price"])`; keep rows where `pd.isna(fav_max)` or `fav_max < threshold_value`.
  - Update label display to use `band_col` for the band shown in the dropdown options (line 262).
- Callback `update_game` (line 301-372): mirror the same Inputs + helper call so band filter for chart loading stays consistent with picker.
- Add `import numpy as np` if not already imported.
- Layout-time `info_row` for "Threshold Default" added under Chart Settings card showing the configured default (read-only display).

**Test strategy:**
- Manual: start `python app.py`, switch anchor → bucket labels update in picker; tipoff_available=False games disappear when anchor=Tip-off.
- Manual: toggle threshold checkbox + change value → game list shrinks immediately; off → list returns.
- Manual: confirm existing deep-link from backtest results page (`bt_game` query param) still resolves under the new control set.
- Add `tests/test_main_dashboard_filters.py`: pure-function test of `_apply_bucket_and_threshold` with synthetic DataFrame asserting each branch (anchor swap, threshold on/off, tipoff_available filter, NaN-preserve).

### Step 6: Stream-game-analytics on-demand sidecar fill
Files: analytics.py
Depends on: Step 4

**What changes:**
- Within `_compute_base_record` (already touched in Step 4), the `load_or_compute_ingame_extremes` call handles both backfilled and on-demand cases — backfill writes the sidecar; on-demand writes if missing.
- Ensure the `game_provider` closure in `_make_lazy_loader` (analytics.py:359-375) exposes the already-loaded `trades_data` so `load_or_compute_ingame_extremes` can avoid a second `gzip.open`. Pass `get_game.get_trades_data` through to `_compute_base_record`'s sidecar call as an optional fast-path argument.
- Document in `ingame_extremes.compute_ingame_extremes` docstring: caller may pass `events` and `trades_df` directly to skip disk reads.

**Test strategy:**
- Run dashboard with empty `cache/<date>/`; first game load writes sidecar; second restart reads it without trades-file read (mock `gzip.open` to count invocations in a unit test).
- Integration: `stream_game_analytics` over a fixture date dir; assert sidecar JSON appears after first iteration.

### Step 7: Documentation update
Files: CLAUDE.md
Depends on: Step 1, Step 4, Step 5

**What changes:**
- Add bullet under "Dashboard & Analytics" structure for `ingame_extremes.py` describing its role + sidecar location.
- Update the bullet describing per-game cache convention to list `ingame_extremes` as the second cache that carries `input_fingerprint` (alongside `nba_tipoff`), and note it's the only one that omits `settings_hash` (settings-independent).
- Document the new base-records columns (`away_in_game_min_price` / `away_in_game_max_price` / `home_in_game_min_price` / `home_in_game_max_price`) and the schema bump to v2.
- Add `chart_settings.json` key `max_favorite_price_threshold` to the relevant Key Patterns bullet.

**Test strategy:**
- Documentation-only; no functional tests. Manual review for accuracy against shipped code.

## Execution Preview

- **Wave 0** (parallel): Step 1, Step 2
- **Wave 1** (parallel): Step 3, Step 4
- **Wave 2**: Step 5, Step 6 (both touch analytics.py / main_dashboard_page.py — but disjoint files; can run in parallel)
- **Wave 3**: Step 7
- Total waves: 4. Max parallelism: 2. Critical path: Step 1 → Step 4 → Step 5 → Step 7.

## Risk Flags

- **Cache pickle regeneration latency.** Step 4's schema bump invalidates all existing `cache/_base_records/*.pkl` on first run. For users with many dates in `data/`, first dashboard load post-deploy will re-stream all games. Recommend running `scripts/backfill_ingame_extremes.py` ahead of time so the per-game sidecars exist before the streaming pass.
- **`_compute_base_record` signature change.** Step 4 extends its parameter list (adds `cache_dir_path`, `data_dir`, optional `trades_data_getter`). Callers within `analytics.py` only — verify no external imports reference it (grep confirmed none).
- **Sidecar write race.** Backfill running concurrently with dashboard could touch the same sidecar. Atomic `os.replace` after tmp-write per `nba_tipoff_cache` pattern is sufficient; reads are JSON-parse-or-discard-on-error.
- **Dash callback overlap.** Step 5 adds three new Inputs to two callbacks that share state. Existing `bucket-picker` id reused, but new inputs add render-on-change cost. Negligible for the typical 100-game frame; flag for revisit if dashboard becomes sluggish.
- **`tipoff_favorite_team` NaN handling.** Threshold filter relies on `analytics[fav_team_col] == analytics["away_team"]`. When the team is None/NaN (sport edge case), `np.where` returns NaN → row is preserved by the `pd.isna(fav_max)` branch. Verified in Step 5 test plan.
- **Sentrux gate:** sentrux installed; advisory architecture gate should run via `/execute-plan` per planning-pipeline.md.

## Open Questions

- Whether to expose `window_quality` in the picker label (e.g. asterisk for `"low"` quality games) — deferred to a follow-up; spec keeps the column persisted but unused by the UI.
- Whether to allow the user to override `gamma_closed_time` cap when they specifically want post-settlement noise included — out of scope; raise if a user requests it.
- Sidecar write contention scenario (backfill + live dashboard touching the same path simultaneously) — atomic rename is believed sufficient; revisit if observed in practice.

## Verification

- Run `pytest tests/test_ingame_extremes.py tests/test_backfill_ingame_extremes.py tests/test_analytics.py tests/test_main_dashboard_filters.py tests/test_nba_tipoff_cache.py` → all green.
- Delete `cache/_base_records/*` and `cache/<date>/*_ingame_extremes.json`. Run `python scripts/backfill_ingame_extremes.py --data-dir data --start-date 2026-04-01 --end-date 2026-04-30` → reports written>0, skipped=0. Re-run same command → reports written=0, skipped=N.
- Start `python app.py`. Toggle Bucket Anchor between Open / Tip-off → picker labels update; games with `tipoff_available=False` vanish under Tip-off. Toggle threshold checkbox + change value to 0.95 → list shrinks; uncheck → restores.
- Open a deep-link `/?bt_game=...` from the backtest results page → resolves correctly under the new control set.
- Confirm CLAUDE.md updates render correctly (raw read).
<!-- toolkit: check=clean waves=clean gate=fired:open-questions,test-strategy-leak mode=feature:tip-off-bucket-and-max-favorite-price-filters -->
