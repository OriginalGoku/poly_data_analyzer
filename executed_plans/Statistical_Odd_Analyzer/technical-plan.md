## Lens status

- Default lens. Feature-driven dispatch from `features/statistical-odd-analyzer/feature.md` (status: `spec-ready`).

## Problem Statement

The existing `/nba-open-tipoff-analysis` page reports unconditional band statistics (e.g., `Tipoff Favorite Win Rate`, `Open Favorite Win Rate`) but does not answer the conditional re-entry question: **given the favorite was in band B at tipoff and its price subsequently dropped X% intraday, what fraction of those games saw price recover to ≥ tipoff before game end?** Without this base rate, the user cannot evaluate whether an in-game dip in a strong-favorite game is a +EV re-entry.

This plan adds a new Dash page `/nba-band-drop-recovery` that runs a sweep of the existing backtest engine (`pct_drop_window` trigger + `reversion_to_open` exit, anchored at tipoff) over drop magnitudes {10..95}%, joins the per-position output to the cached base-records frame to attach `open_interpretable_band`, and renders a 2D grid of recovery rate + N + Wilson 95% CI + median time-to-recovery + median further-drawdown.

Scope per the feature spec: NBA only, favorite-only, no PnL/fees rendered, additive (no changes to existing analytics or engine modules), v1 has no persistent aggregated-cell cache.

## Codebase Context

**Existing primitives (all verified, no code changes required):**
- `backtest/triggers/pct_drop_window.py:22-85` — `anchor="tipoff"` supported via `ctx.tipoff_prices`; first-touch via `hits.iloc[0]`.
- `backtest/exits/reversion_to_open.py:15-41` — reverts to `trigger.anchor_price` (which is the tipoff price when anchor=tipoff); compares `price >= target`.
- `backtest/scenarios.py:24-43` — generic `{"sweep": [...]}` node expansion via `itertools.product`; produces N scenarios from one JSON.
- `backtest/runner.py:311` — `run(scenarios, start_date, end_date, data_dir, settings, ...) -> (per_position_df, aggregation_df)`. Per-position rows include `date`, `match_id`, `entry_team`, `exit_kind`, `entry_time`, `exit_time`, `entry_price`, `exit_price`, `scenario_name`, and `sweep_axis_*` columns.
- `backtest/contracts.py:46-56` `GameMeta` — already carries `tipoff_fav_price` (NaN-fallback to `open_fav_price` per `first_k_above.py:120-122`).
- `backtest/filters/first_k_above.py:38` — permissive universe filter usable as-is with `k=1, min_price=0.0` (or similar) to enumerate all NBA games with valid tipoff data.
- `analytics.py:91-98` `INTERPRETABLE_BANDS` constant + `analytics.py:49,68` `_load_base_records_cache` / `_save_base_records_cache` / `_base_records_settings_hash` — base-records pickle at `cache/_base_records/<hash>.pkl` with `open_interpretable_band` per game.
- `nba_analysis.py:1156` `_wilson_interval(rate, n, z=1.96) -> (lo, hi)` — reusable for cell CIs.
- `pages/nba_open_tipoff_page.py:26-34` — page class shape (`route`, `title`, `__init__(analysis_service, settings)`, `layout`, `register_callbacks`); duplicates `INTERPRETABLE_BANDS` as local `BAND_DEFINITIONS` (lines 16-23) — new page must source from `analytics.py` directly per feature R13.
- `app.py:13,27,37-43,62-68` — page registration pattern: import class, instantiate, add to route dict, call `register_callbacks(app)`.
- `view_helpers.py:52` `build_navbar(active_path)` — must add the new route to the navbar `links` list.

### Reusable-Code Survey

- `pct_drop_window` (`backtest/triggers/pct_drop_window.py:22-85`) — exact drop detector. Reused as-is.
- `reversion_to_open` (`backtest/exits/reversion_to_open.py:15-41`) — exact recovery detector when anchor=tipoff. Reused as-is.
- `{"sweep": [...]}` expansion (`backtest/scenarios.py:24-43`) — fans out drop_pct buckets. Reused as-is.
- `backtest/runner.py:311 run()` — orchestrates the sweep. Reused as-is.
- `first_k_above` (`backtest/filters/first_k_above.py:38`) — permissive NBA universe enumeration. Reused with relaxed params (`k=1, min_price=0.50`, `exclude_inferred_price_quality=False` so the page-level price-quality filter is the source of truth).
- `_wilson_interval` (`nba_analysis.py:1156`) — cell CIs. Imported.
- `_load_base_records_cache` (`analytics.py:49`) — band attribution. Imported.
- `INTERPRETABLE_BANDS` / `ACTIVE_INTERPRETABLE_BAND_LABELS` (`analytics.py:91-102`) — canonical band ordering. Imported.
- `pages/nba_open_tipoff_page.py` — page class shape for visual + filter parity. Pattern-only reuse.
- `view_helpers.py:CARD_STYLE`, `info_row`, `build_navbar` — UI primitives. Imported.

Searched: backtest/, pages/, analytics.py, nba_analysis.py, app.py, view_helpers.py, dip_recovery.py, regime_transitions.py. Repo grounding entries consulted from `features/statistical-odd-analyzer/feature.md`: `probe @ 2026-05-16`, `intake @ 2026-05-16`, `design @ 2026-05-16` — all verified fresh against the current tree.

## Pre-Change Baseline

- `/nba-open-tipoff-analysis` renders today with per-band counts and unconditional band win rates.
- No page in the app answers the conditional recovery question (verified by searching `pages/` — no file references `recovery`, `band_drop`, or `drop_recovery` as a page concept).
- `backtest/scenarios/` contains four scenario files; none target the band-drop-recovery analysis (verified via `/bin/ls backtest/scenarios/`).
- `_wilson_interval` is the only Wilson CI helper in the codebase (verified via grep).

## Verification Signal

This plan is complete when every acceptance criterion A1–H3 in `features/statistical-odd-analyzer/feature.md` is verifiable, specifically:

- Route `/nba-band-drop-recovery` reachable from the running Dash app; renders without errors (A1).
- Methodology card states relative-drop, first-touch, cumulative, strict-tipoff recovery, buffer inclusion, base-rate-only disclaimer (A2).
- Tipoff page band panel includes a link to the new route (A3).
- Filters (date range, price quality, min open favorite price, `min_n_display`) work and rebuild the grid (B1–B4, D3).
- Run summary shows total / excluded-for-missing-tipoff / grid-N, summing correctly (C1–C2).
- Grid rows = 5 active bands in canonical order; columns = [10..95]; cells follow N rendering rules (D1–D6).
- Per-bucket detail table columns and stats match `_wilson_interval` and the medians defined in the spec (E1–E4).
- Aggregator uses engine output only (no parallel price-scanning) and discards PnL columns (F1, F3).
- Bands sourced from cached base-records frame, not recomputed (F2).
- Empty range, malformed scenario file, missing base-records pickle all surface gracefully (G1–G2, G4, TS12).
- Existing tipoff page behavior unchanged except for the link (H1–H3).
- Test scenarios TS1–TS18 pass (subset run as unit/integration tests; manual UI verification for TS1, TS15, TS16).

## Implementation Steps

### Step 1: Add sweep scenario file
Files: backtest/scenarios/band_drop_recovery_sweep.json, tests/test_band_drop_recovery_scenario.py
Depends on: none

**What changes:**
- New JSON scenario file at `backtest/scenarios/band_drop_recovery_sweep.json`.
- `universe_filter`: `first_k_above` with `k=1, min_price=0.50, exclude_inferred_price_quality=false` (page-level filters apply later; the sweep universe is intentionally permissive so the same engine run feeds every page-side filter combination).
- `side_target`: `"favorite"`.
- `trigger`: `pct_drop_window` with `anchor="tipoff"`, `drop_pct={"sweep": [10,20,30,40,50,60,70,80,90,95]}`.
- `exit`: `reversion_to_open` with empty `params`.
- `lock`: `{"mode":"sequential","max_entries":1,"cool_down_seconds":0,"allow_re_arm_after_stop_loss":false}` — one entry per (game, scenario) by construction; first-touch semantics.
- `fee_model`: `"taker"` (required by `REQUIRED_KEYS` in `backtest/scenarios.py:13-21`; the aggregator discards PnL/fee columns).
- New scenario-loading test asserting the sweep expands to exactly 10 scenarios with `drop_pct` set to each value in `[10..95]`.

**Test strategy:**
- Unit: load via `backtest/scenarios.py:load_scenarios`, assert it expands to exactly 10 scenarios named `band_drop_recovery_sweep__trigger.params.drop_pct=<X>`, each with `trigger.params["drop_pct"] == X`.

### Step 2: Build the aggregator module
Files: band_drop_recovery.py, tests/test_band_drop_recovery.py
Depends on: Step 1

**What changes:**
- New top-level module `band_drop_recovery.py` (sibling to `dip_recovery.py`; distinct name per feature R15).
- Public function `compute_recovery_grid(positions_df, base_records_frame, active_bands, drop_pcts, *, min_n_display=5) -> dict[str, pd.DataFrame]`:
  - Joins `positions_df` ← `base_records_frame` on `(date, match_id)` to attach `open_interpretable_band`.
  - Drops positions whose joined band is null or `"Toss-Up"` (defensive; tipoff page already excludes Toss-Up).
  - Extracts `drop_pct` from `sweep_axis_trigger.params.drop_pct` column produced by the runner.
  - For each `(band, drop_pct)` group, computes:
    - `N` = group size,
    - `successes` = count where `exit_kind == "reversion"`,
    - `recovery_rate` = successes / N,
    - `(wilson_lo, wilson_hi)` via `_wilson_interval` from `nba_analysis`,
    - `median_time_to_recovery_seconds` over recovered rows: `(exit_time - entry_time).total_seconds()`,
    - `median_further_drawdown_pct` over all rows: `(entry_price - min_price_post_entry) / entry_price` — `min_price_post_entry` derived from per-position `max_drawdown_cents` already emitted by the runner (`backtest/runner.py:128-146`; `min_price = entry_price - max_drawdown_cents/100`).
  - Returns `{"grid": <wide pivot DataFrame>, "detail": <long-form DataFrame>}`.
- Public function `compute_band_totals(base_records_frame, valid_match_ids) -> pd.DataFrame` — per-band denominators before drop conditioning, restricted to games with a valid favorite tipoff price.
- Public function `partition_games(base_records_frame, filters) -> dict` — returns `{"total": N, "excluded_missing_tipoff": M, "kept_match_ids": set[(date, match_id)]}` for the run-summary card.
- No imports from `dip_recovery.py`; no shared cache files.

**Test strategy:**
- Unit with synthetic positions DataFrame and base-records frame:
  - TS2 fixture: one Upper Strong game that triggered at 10/20/30 and recovered → cells at 10/20/30 = 100% (1); cell at 40 = 0% (0) → renders as `—` upstream.
  - TS5: blow-out game (no recovery) → cell shows 0% with positive N.
  - TS13 cumulative invariant: shallow N ≥ deeper N within the same band.
  - TS14: two games at (band, 20), one recovers → 50% (2) with Wilson CI matching `_wilson_interval(1, 2)`.
  - Empty input → returns shaped-but-empty grid (TS7).
  - Verify no PnL/ROI columns in the returned DataFrames (F3).

### Step 3: Build the Dash page
Files: pages/nba_band_drop_recovery_page.py, tests/test_nba_band_drop_recovery_page.py
Depends on: Step 2

**What changes:**
- New page class `NBABandDropRecoveryPage` modeled on `NBAOpenTipoffAnalysisPage` (`pages/nba_open_tipoff_page.py:26`):
  - `route = "/nba-band-drop-recovery"`, `title = "NBA Band Drop Recovery"`.
  - `__init__(self, settings)` — no `analysis_service` dependency; page owns its own runner invocation.
  - `layout(self)` — methodology card (text per A2), filter row (date range, price quality dropdown, min open favorite price input, `min_n_display` input, sport label locked to NBA, read-only pregame settings display), Run button, run-summary card, grid `dash_table.DataTable`, collapsible per-bucket detail table.
  - `register_callbacks(self, app)`:
    - Single callback triggered by the Run button (and initial mount); reads filter values, computes `settings_hash` matching `_base_records_settings_hash`, loads base-records via `_load_base_records_cache`, applies sport=`nba` + date range + price-quality + min-price filters → produces `valid_match_ids` and the partition summary; on missing base-records cache returns a visible error message (TS12) without crashing.
    - Calls `backtest.runner.run([scenarios from band_drop_recovery_sweep.json], start_date, end_date, data_dir, settings)`; on missing/malformed scenario file returns a visible error message (TS10/TS11/G2).
    - Filters resulting positions to `valid_match_ids`.
    - Calls `compute_recovery_grid` from Step 2; renders grid + detail tables.
    - Cell rendering: `N == 0 → "—"`, `0 < N < min_n_display → "{rate:.0%}* (N)"` with dimmed style, else `"{rate:.0%} (N)"`.
- Imports `INTERPRETABLE_BANDS`, `ACTIVE_INTERPRETABLE_BAND_LABELS` from `analytics.py` (R13). Does NOT redefine the band list locally.

**Test strategy:**
- Unit: import the page, instantiate, call `layout()` and assert it returns a `Div` containing controls keyed for the callback; assert the page's required IDs match those wired in `register_callbacks` (smoke-style, matches existing page tests).
- Integration: monkeypatch `backtest.runner.run` to return a small fixture positions DataFrame; trigger the callback and assert the returned grid table includes the expected rows/columns and N values.
- Manual: TS1 — start `python app.py`, navigate to `/nba-band-drop-recovery`, verify grid populates and cells render per D1–D6.

### Step 4: Wire the page into the app shell
Files: app.py, view_helpers.py, tests/test_app_routes.py
Depends on: Step 3

**What changes:**
- `app.py`: import `NBABandDropRecoveryPage`, instantiate with `chart_settings`, add to `PAGES` route dict, call `band_drop_recovery_page.register_callbacks(app)`.
- `view_helpers.py:52 build_navbar`: append `("NBA Band Drop Recovery", "/nba-band-drop-recovery")` to the `links` list.
- New routes test (or extend existing) asserting the route is in `PAGES` and the navbar `links` list.

**Test strategy:**
- Unit: assert the new route is present in `PAGES` and the navbar `links` list.
- Manual: TS16 — navigate to `/nba-band-drop-recovery` from the navbar and back; both pages render.

### Step 5: Add link from tipoff page band-reference panel
Files: pages/nba_open_tipoff_page.py
Depends on: Step 4

**What changes:**
- In `NBAOpenTipoffAnalysisPage.layout`, within the existing band-reference panel block (around the `BAND_DEFINITIONS` rendering), append a single `dcc.Link("View Drop-Recovery Grid →", href="/nba-band-drop-recovery", ...)` with consistent styling.
- No other behavior changes; band rendering, filters, callbacks untouched (H1).

**Test strategy:**
- Unit: assert the layout HTML produced by the tipoff page contains a Link with `href="/nba-band-drop-recovery"`.
- Manual: TS3 — verify the link is visible on the band-reference panel and navigates to the new page; tipoff page state remains intact when returning.

### Step 6: Integration test — end-to-end sweep against a fixture
Files: tests/test_band_drop_recovery_e2e.py, tests/fixtures/band_drop_recovery/
Depends on: Step 2, Step 3

**What changes:**
- Build a minimal fixture data directory under `tests/fixtures/band_drop_recovery/` (or reuse an existing test data dir) containing 2–3 synthetic NBA games covering: an Upper Strong game that drops 30% and recovers, a Lower Moderate game that drops 50% and does not recover, a game with missing tipoff price.
- Run `backtest.runner.run([sweep scenario], ...)` end-to-end, run `compute_recovery_grid`, and assert: TS2 (cells), TS4 (excluded count), TS13 (cumulative invariant), TS15 (band totals match `analytics` view for the same filter set).

**Test strategy:**
- Pytest integration test using the fixture; no Dash callback layer required (callback is exercised in Step 3 tests).

### Step 7: Update CLAUDE.md page registry section
Files: CLAUDE.md
Depends on: Step 4

**What changes:**
- Under the "Structure → UI pages" notes, add a one-liner entry: `pages/nba_band_drop_recovery_page.py` — Band × drop-pct recovery grid (route `/nba-band-drop-recovery`).
- Add a one-liner under "Backtest Framework → New Backtest Engine → scenarios" noting the new `band_drop_recovery_sweep.json` scenario.

**Test strategy:**
- Doc-only; visual review.

## Execution Preview

- **Wave 0 (parallel):** Step 1 (scenario JSON + scenario test).
- **Wave 1:** Step 2 (aggregator + unit tests) — depends on Step 1.
- **Wave 2:** Step 3 (Dash page + page test) — depends on Step 2.
- **Wave 3:** Step 4 (app wiring + routes test) — depends on Step 3.
- **Wave 4 (parallel):** Step 5 (tipoff link) + Step 6 (e2e test) + Step 7 (CLAUDE.md) — touch disjoint files.
- **Total waves:** 5. **Max parallelism:** 3 (Wave 4). **Critical path:** Step 1 → Step 2 → Step 3 → Step 4 → Step 5/6/7.

## Risk Flags

- **Aggregator's `min_price_post_entry` derivation depends on `max_drawdown_cents`.** If `max_drawdown_cents` is NaN or negative, the median further-drawdown becomes garbage. Mitigation: aggregator coerces NaN → 0 and clamps negatives to 0 before computing the median.
- **Engine run time on the full archive × 10 buckets is unmeasured.** No persistent aggregated-cell cache in v1 (R17). If render takes > a few seconds, the page should gain a result memoization keyed by (settings_hash, date range, price_quality, min_price) — v1.1 follow-up, not v1 blocker.
- **`first_k_above` always calls `load_game` per candidate (`backtest/filters/first_k_above.py:84`).** This is the engine's existing cost, not new — but the permissive `k=1, min_price=0.50` settings make the universe larger than current scenarios use, so the engine sweep will read more games than backtest-results pages typically do.
- **`reversion_to_open` is named for its anchor-name-from-the-scenario-that-introduced-it, not its semantics.** The plan uses it with `anchor="tipoff"`. This is correct (the exit reads `trigger.anchor_price`, which is set from whatever the trigger anchored on). Documented in the methodology card and in `band_drop_recovery.py` module docstring to prevent future confusion.
- **`Toss-Up` band defensive filter in Step 2.** The tipoff page already excludes Toss-Up via the `min_price` filter; the aggregator drops it again as belt-and-suspenders. If the user later loosens `min_price`, this guard prevents Toss-Up from accidentally appearing in the grid.
- **Sentrux gate:** the project has `sentrux` available. Run `/architecture-gate compare` after Step 6 to confirm no structural regression; advisory only.

## Open Questions

None.

## Verification

- Unit tests pass: `pytest tests/test_band_drop_recovery_scenario.py tests/test_band_drop_recovery.py tests/test_nba_band_drop_recovery_page.py tests/test_band_drop_recovery_e2e.py tests/test_app_routes.py` (new files from Steps 1–6).
- Existing suite green: `pytest` from repo root.
- Manual UI smoke: `python app.py`, navigate to `/nba-band-drop-recovery`, exercise TS1 / TS15 / TS16 / TS8 by hand.
- Sentrux advisory: `/architecture-gate compare` produces no critical regression (advisory only).
- Acceptance criteria A1–H3 verified per the per-criterion test mapping in Verification Signal.
<!-- toolkit: check=clean waves=clean gate=clean mode=feature:statistical-odd-analyzer -->
