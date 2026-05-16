# Statistical Odd Analyzer

- **slug:** statistical-odd-analyzer
- **status:** spec-ready
- **created:** 2026-05-16
- **updated:** 2026-05-16

## Summary

A new Dash page that reports, for each open-favorite interpretable band, the empirical probability that the in-game favorite price recovers to its tipoff value after first touching a given relative drop magnitude. Output is a 2D table (band × drop-pct) of recovery rate + supporting statistics, derived from a sweep run of the existing scenario backtest engine.

## Problem

The current `/nba-open-tipoff-analysis` page exposes static per-game and per-band aggregates (e.g., `Tipoff Favorite Win Rate`, `Open Favorite Win Rate`) but does not answer the conditional question that drives in-game re-entry decisions: **given the favorite was in band B at tipoff and its price subsequently dropped X% intraday, what fraction of those games saw price recover to ≥ tipoff before game end?**

Without this base rate the user cannot tell whether an in-game dip in a strong-favorite game represents a +EV entry or just noise. The unconditional band win rate (e.g., 91% for Upper Strong) is the wrong reference once a drop has occurred — survivorship bias makes the post-drop population behave differently.

## Desired Outcome

A page that displays:

- A grid: rows = the five active interpretable bands (Lean / Lower Moderate / Upper Moderate / Lower Strong / Upper Strong), columns = drop magnitudes {10, 20, …, 95}%.
- Each cell: recovery rate, N, Wilson 95% CI, median time-to-recovery, median further-drawdown.
- Cumulative bucket semantics (a game that dropped 50% contributes to all of {10…50}); first-touch detection per bucket.
- Games lacking a tipoff price for the favorite are excluded from every cell, with the excluded count surfaced separately so denominators stay interpretable.

Interpretation: each cell answers `P(touch ≥ tipoff_price before game end | favorite price first touched ≤ (1 − X) × tipoff_price)` — a base rate for evaluating whether an in-game entry at the X% drop level has positive EV against the post-drop market price.

## Repo Fit

The computation is a thin reuse of existing primitives — no new price-scanning code is required:

- **Drop detection:** `backtest/triggers/pct_drop_window.py:22-85` already supports `anchor="tipoff"` and computes `target_price = anchor_price * (1 - drop_pct/100)`. First-touch via `hits.iloc[0]`.
- **Recovery detection:** `backtest/exits/reversion_to_open.py:15-41` triggers on the first post-entry trade with `price >= trigger.anchor_price`. With `anchor="tipoff"` the recovery target is the tipoff price (despite the exit's name).
- **Sweep mechanism:** `backtest/scenarios.py:24-43` recognizes `{"sweep": [...]}` at any node; a single sweep over `trigger.params.drop_pct` fans out to ten scenarios in one engine run.
- **Band assignment:** `analytics.py:91-98` defines `INTERPRETABLE_BANDS`; the band per game is already materialized in the base-records frame cached at `cache/_base_records/<settings_hash>.pkl` (per CLAUDE.md). Aggregator joins engine positions ← base_records on (date, match_id).
- **Page pattern:** `pages/scenario_results_page.py` shows how to render scenario-engine output; a new page (`pages/statistical_odd_analyzer_page.py`) models the pivot view distinctly because the 2D grid is not the same shape as per-scenario results.
- **Stats helper:** `_wilson_interval` already exists in `nba_analysis.py`.

Out-of-scope reuse candidate: `dip_recovery.py` solves a different problem (absolute price thresholds for micro-prices, per-token, no anchor concept) and is not repurposed.

## Scope

**In scope (v1):**
- NBA only (matches the existing tipoff analysis page; bands as currently defined).
- Favorite side only (no underdog symmetric analysis).
- Drop set: {10, 20, 30, 40, 50, 60, 70, 80, 90, 95}%.
- Cell stats: recovery rate, N, Wilson 95% CI, median time-to-recovery (seconds), median further-drawdown (% below entry).
- Explicit exclusion + reported count for games missing a favorite tipoff price.
- New Dash page (route TBD in design mode).

**Out of scope (v1):**
- Underdog drops.
- Non-NBA sports.
- EV calculation against post-drop market price (page reports base rate only; EV interpretation left to user).
- Multi-touch / non-cumulative bucketing variants.
- Settlement PnL columns (this is a descriptive stats page, not a backtest results view).
- Custom band editing (uses existing `INTERPRETABLE_BANDS` constant).
- Persistent aggregated-cell cache (decide in design if needed; v1 may recompute on page load).

## Actors

- **Primary actor:** the project owner, evaluating in-game NBA favorite re-entries on Polymarket. Uses the page to look up the historical recovery rate for the (band, drop) cohort matching a live game, then compares against the current market price to decide whether to enter.
- **No secondary actors.** Single-user tool; no auth, no sharing, no notifications.

## Workflow / Behavior

**Entry point.** User navigates to a new route under the existing Dash app, sibling to `/nba-open-tipoff-analysis`. Proposed route: `/nba-band-drop-recovery`. A link is added to the band-reference panel on the existing tipoff page.

**Page controls (shared filter semantics with `/nba-open-tipoff-analysis`):**
- Sport: fixed to `nba` for v1 (selector hidden or disabled).
- Date range: start/end date pickers, defaulting to the full available NBA archive.
- Price Quality: `all | exact | inferred` (same as tipoff page).
- Minimum open favorite price: numeric input (same as tipoff page).
- Pregame open settings (`pregame_min_cum_vol`, anchor stat, anchor window): read-only display of values in effect, sourced from `chart_settings.json`; not adjustable on this page (matches existing convention).
- A single "Run / Refresh" action button.

**Output sections (top to bottom):**

1. **Run summary card.** Total NBA games matching the date + price-quality + min-price filters; count excluded for missing favorite tipoff price; remaining N feeding the grid.
2. **Recovery grid.** Pivot table, rows = active bands in canonical order (Lean Favorite, Lower Moderate, Upper Moderate, Lower Strong, Upper Strong), columns = drop magnitudes (10, 20, 30, 40, 50, 60, 70, 80, 90, 95). Each cell shows `recovery_rate% (N)` as primary text. Hover/expand surfaces the supporting stats (Wilson CI low/high, median time-to-recovery in seconds, median further-drawdown as % below entry). Cells with `N == 0` render as `—`. Cells with `N < min_n_display` (default 5; configurable on page) render the rate dimmed with an asterisk.
3. **Band totals column.** Right-most column: `band_total_games` (denominator before any drop conditioning).
4. **Per-bucket detail table (collapsible).** One row per `(band, drop_pct)` cell, columns: band, drop_pct, N, recovery_rate, wilson_lo, wilson_hi, median_time_to_recovery_seconds, median_further_drawdown_pct. Useful for export and audit.

**Computation flow (per page render):**

1. Resolve active filters → derive `settings_hash` matching the existing analytics layer.
2. Load base-records frame from `cache/_base_records/<settings_hash>.pkl`; restrict to `sport == "nba"` and the date range.
3. Apply the same filters that the tipoff page uses (price quality, min open favorite price). Result: candidate game set with `open_interpretable_band` per game.
4. Drop games where the favorite tipoff price is missing or null. Record the excluded count.
5. Load the sweep scenario at `backtest/scenarios/band_drop_recovery_sweep.json` (new file, v1). Run via existing `backtest/runner.py` over the same date range. Engine produces a positions DataFrame across all ten drop_pct scenarios.
6. Join positions ← surviving base-records on (`date`, `match_id`) to attach `open_interpretable_band` and the favorite `tipoff_price`.
7. Aggregate: for each (band, drop_pct) cell, compute `recovery_rate = mean(exit_kind == "reversion")`, N, Wilson CI, median time-to-recovery in seconds (`exit_time - entry_time` over recovered positions), median further-drawdown (per-position `(entry_price - min_price_post_entry) / entry_price`, over all positions in the cell).
8. Pivot to the grid view; emit per-bucket detail rows alongside.

**No PnL, no fees.** This page does not render settlement payout, ROI, or fee-adjusted columns from the engine even though the engine computes them — they're irrelevant to the base-rate question and would mislead.

## Rules And Decisions

| ID | Rule | Notes |
|---|---|---|
| R1 | Sport is NBA only in v1. | Other sports lack the same band stability assumptions; extension is a future feature. |
| R2 | Side is favorite only. | Mirrors existing tipoff page; underdog symmetric variant is out of scope. |
| R3 | Drop magnitude is **relative**: `target = tipoff_price * (1 - drop_pct/100)`. | Confirmed by user; matches `pct_drop_window` trigger semantics. |
| R4 | Drop detection is **first-touch** per bucket. | Each scenario's trigger fires once per game (`hits.iloc[0]`). |
| R5 | Buckets are **cumulative**. | Achieved automatically by running ten independent drop_pct scenarios; a deeper-drop game appears in every shallower bucket via its own scenario hit. |
| R6 | Recovery target is **strict tipoff price**, not band re-entry. | `reversion_to_open` exit compares `price >= trigger.anchor_price`. |
| R7 | Recovery window is **trigger_time to game_end inclusive of `post_game_buffer_min`**, matching engine convention. | Documented as a known semantic; surfaced in the methodology card on the page. |
| R8 | Games missing favorite tipoff price are **excluded from every cell**, with the excluded count surfaced in the run summary. | Prevents silent denominator shrinkage. |
| R9 | Game-end boundary uses **engine's `Context.game_end`** (last score event + `post_game_buffer_min`). | Same definition used by `_compute_in_game_open_favorite_metrics`. |
| R10 | Cell stats: recovery_rate, N, Wilson 95% CI, median time-to-recovery (seconds), median further-drawdown (% of entry price). | Confirmed by user. |
| R11 | Cells with `N < min_n_display` are rendered dimmed with an asterisk; `min_n_display` default = 5, configurable on the page. | Surfaces sample-size cliff explicitly. |
| R12 | Cells with `N == 0` render as `—`. | Distinct from "low confidence". |
| R13 | Bands are sourced from `INTERPRETABLE_BANDS` in `analytics.py`; Toss-Up is excluded (matches existing tipoff page filter). | Single source of truth — do not duplicate band definitions in the new page. |
| R14 | Active band assignment is read from the cached base-records frame; the page does NOT recompute bands. | Avoids drift between this page and `/nba-open-tipoff-analysis`. |
| R15 | New module/page must not collide semantically with `dip_recovery.py`. | Use the `band_drop_recovery` naming family for files, scenarios, and routes. |
| R16 | The page presents base rates only. It does **not** compute EV against post-drop market price. | Explicitly documented in the methodology card. |
| R17 | No persistent aggregated-cell cache in v1. Recompute on page load; rely on the backtest engine's per-game loading (and the base-records pickle) for speed. | Revisit if measured page render exceeds a few seconds. |
| R18 | Universe filter for the sweep scenario must be permissive (no `min_price` restriction beyond what the tipoff page filters already imposed). | The page-level filter is the source of truth; the scenario universe filter just enumerates the games. |
| R19 | The page reuses the existing tipoff-page filter UI components where possible to keep behavior identical. | Visual + filter parity with the sibling page. |
| R20 | Engine's PnL/ROI/fee columns are computed but discarded by the aggregator. | They're irrelevant to the descriptive stat being reported. |

## Edge Cases

- **Game with no in-game trades on the favorite token.** Trigger returns None for every bucket → game contributes to band total but to no (band, drop) cell. Acceptable; engine semantics already handle.
- **Game where tipoff price is missing but the game otherwise has trades.** Excluded entirely per R8. Counted in "excluded for missing tipoff price".
- **Game where favorite price drops to 0 (e.g., blow-out loss).** Trigger fires for every bucket up to and including the deepest reached; reversion exit never fires; cells correctly record as non-recovery.
- **Game where favorite price never moves below tipoff.** No trigger fires for any bucket; contributes only to band total, not to any cell.
- **Game where price touches X% drop exactly at game_end.** Engine slices `sliced["datetime"] < ctx.game_end`; boundary tick is excluded. Acceptable.
- **Game with favorite-side switch intraday.** The new page tracks the **open-favorite token**, not the dynamically-favored token. A favorite switch does not change the token being priced. Document on the page.
- **Game in regulation overtime.** `post_game_buffer_min` (default 10 from CLAUDE.md notes) extends the window past last score event; OT games that finish within the buffer are captured. Games whose OT extends beyond the buffer may have their tail trades excluded — known limitation.
- **Date range with zero NBA games.** Run summary shows zeros across all cells; grid renders as all `—`. No error.
- **Settings change between page loads.** A new `settings_hash` directs the base-records loader to a different pickle; aggregation rebuilds from scratch. No cross-settings contamination.
- **Engine sweep produces zero positions for a deep bucket (e.g., 95%).** Cell shows `0% (N)` if any games triggered but none recovered, or `—` if no games triggered. Wilson CI on N=0 of zero recovered is reported as `[0, 0]` and visually dimmed.
- **Sweep scenario file missing or malformed.** Page surfaces an explicit error in the run-summary card; does not crash silently.
- **User picks a date range smaller than the cached base-records range.** Filter operates on the in-memory frame; no recomputation of base records. Fast path.

## Acceptance Criteria

**Grouped by user-facing outcome. Each criterion is independently testable.**

### A. Page presence and discoverability
- A1. A new Dash route `/nba-band-drop-recovery` is reachable from the running app and renders without errors.
- A2. The new page exposes a title and a methodology card stating: relative-drop semantics, first-touch, cumulative buckets, strict-tipoff recovery target, `post_game_buffer_min` inclusion, and the "base rate only — not EV" disclaimer.
- A3. The band-reference panel on `/nba-open-tipoff-analysis` includes a visible link/button leading to `/nba-band-drop-recovery`.

### B. Filter behavior
- B1. The page exposes controls for date range, price quality (`all|exact|inferred`), and minimum open favorite price; defaults match those of `/nba-open-tipoff-analysis`.
- B2. Changing any filter and re-running rebuilds the grid against the filtered game set; no stale rows from a prior filter remain visible.
- B3. Pregame open settings (`pregame_min_cum_vol`, anchor stat, anchor window) are displayed read-only with values sourced from `chart_settings.json`.
- B4. The sport selector (if present) is locked to NBA in v1.

### C. Run summary card
- C1. The run summary shows: total NBA games matching filters, count excluded for missing favorite tipoff price, remaining N feeding the grid.
- C2. Excluded-count + grid-N equals total-matching-games for every filter combination.

### D. Recovery grid
- D1. Grid rows correspond exactly to the five active interpretable bands in canonical order (Lean Favorite, Lower Moderate, Upper Moderate, Lower Strong, Upper Strong). Toss-Up is not shown.
- D2. Grid columns are exactly: 10, 20, 30, 40, 50, 60, 70, 80, 90, 95 — labeled as percentages.
- D3. Each cell shows recovery rate (as a percent) and N. Cells with `N == 0` render as `—`. Cells with `0 < N < min_n_display` render dimmed with a trailing asterisk; `min_n_display` defaults to 5 and is changeable via a numeric input on the page.
- D4. A right-most "Band Total" column shows the per-band denominator (games with valid tipoff price, before any drop conditioning).
- D5. For any (band, drop_pct) cell with `N > 0`, recovery rate equals `count(positions where exit_kind == "reversion") / N` for that cell.
- D6. Cumulative-bucket invariant: for any band B and drop levels `X1 < X2`, `N(B, X1) >= N(B, X2)` for all observed data (deeper drops are a subset of shallower drops).

### E. Per-bucket detail table
- E1. Below the grid, a collapsible table renders one row per (band, drop_pct) cell with columns: band, drop_pct, N, recovery_rate, wilson_lo, wilson_hi, median_time_to_recovery_seconds, median_further_drawdown_pct.
- E2. `wilson_lo` and `wilson_hi` agree with `_wilson_interval(successes, N)` from `nba_analysis.py` to within floating-point tolerance.
- E3. `median_time_to_recovery_seconds` is computed only over recovered positions; if zero positions recovered in a cell, it renders blank.
- E4. `median_further_drawdown_pct` is computed over all positions in the cell (recovered + non-recovered), as `(entry_price - min_price_post_entry) / entry_price`.

### F. Computation correctness vs. engine
- F1. The page uses the existing scenario engine (`backtest/runner.py`) via a sweep scenario file at `backtest/scenarios/band_drop_recovery_sweep.json`; no parallel price-scanning code path exists in the new page or aggregator.
- F2. Band assignment per game is sourced from the cached base-records frame (`cache/_base_records/<settings_hash>.pkl`); the new page does not recompute bands.
- F3. The aggregator discards engine PnL/ROI/fee columns; none of these values surface in any UI element on the new page.

### G. Robustness
- G1. Empty date range or zero matching games renders the grid as all `—` with no exception.
- G2. A missing or malformed `backtest/scenarios/band_drop_recovery_sweep.json` is surfaced as a visible error message in the run-summary card; the page does not crash.
- G3. Page render time on a full available NBA archive completes without browser timeout under default settings.
- G4. Changing settings (`pregame_min_cum_vol`, etc.) and reloading the page produces results consistent with the new `settings_hash` — no cross-settings contamination.

### H. Existing surfaces unaffected
- H1. `/nba-open-tipoff-analysis` continues to render and behave identically except for the new link added to the band-reference panel.
- H2. No existing scenario JSON file is modified.
- H3. No changes to `analytics.py`, `dip_recovery.py`, or any backtest engine module are required to ship v1.

## Test Scenarios

### Happy path
- TS1. Date range covering ≥30 days of NBA games, default filters, default `min_n_display`. Expect: grid populated, no `—` in the 10–40 columns for any band with > 0 games, Band Total column matches sum of per-band counts.
- TS2. Synthetic dataset (fixture or recorded subset) where one Upper Strong game drops 30% then recovers. Expect: cell `(Upper Strong, 10)`, `(Upper Strong, 20)`, `(Upper Strong, 30)` all report `100% (1)`; cell `(Upper Strong, 40)` reports `—`.

### Edge cases
- TS3. Synthetic game with no in-game favorite trades. Expect: contributes to no cell; does NOT appear in excluded count (excluded count tracks only missing-tipoff-price, not missing-in-game-trades).
- TS4. Synthetic game with missing favorite tipoff price. Expect: counted in "excluded for missing tipoff price"; does not contribute to any cell or band total.
- TS5. Synthetic game where favorite price drops to 0 and stays there. Expect: triggers fire for buckets up to the deepest reached; cells record as non-recovery; further-drawdown reflects max possible.
- TS6. Synthetic game where favorite price touches tipoff exactly at the post-buffer game_end timestamp. Expect: behaves per engine's `< ctx.game_end` slice (boundary tick excluded); no special-case handling required.
- TS7. Date range with zero matching NBA games. Expect: grid all `—`, run-summary N=0, no exception.
- TS8. Cell with `N == 3` and `min_n_display = 5`. Expect: rate is shown dimmed with asterisk. Lowering `min_n_display` to 3 redraws the cell un-dimmed.
- TS9. Cell with `N == 0`. Expect: renders `—`, not `0%`.

### Failure / malformed input
- TS10. Scenario file deleted. Expect: run-summary card shows explicit error message; no crash.
- TS11. Scenario file present but JSON-invalid. Expect: explicit error message; no crash.
- TS12. Base-records pickle missing for current `settings_hash`. Expect: page surfaces a message indicating analytics base records have not been built for the current settings; no crash.

### Precedence / overlap
- TS13. Game that triggers the 50% scenario also triggers each of 10/20/30/40. Verify it contributes once to each shallower cell's N (cumulative invariant D6).
- TS14. Two games in the same band where one recovers from 20% and the other does not. Cell `(band, 20)` shows `50% (2)`; Wilson CI matches `_wilson_interval(1, 2)`.

### Regression-sensitive behavior
- TS15. Compare per-band totals on the new page to per-band counts shown on `/nba-open-tipoff-analysis` for the same filter set — they must match (modulo the missing-tipoff-price exclusion, which the new page reports separately).
- TS16. Tipoff page link verified to navigate to `/nba-band-drop-recovery` and back without losing state on the tipoff page.
- TS17. Running the sweep scenario directly via `backtest_cli` (or equivalent runner entry point) produces positions whose aggregation matches the page's grid exactly.
- TS18. Renaming or moving `pct_drop_window` / `reversion_to_open` would break this page — pinned as a known dependency in `Technical Notes`.

## Technical Notes

Decisions already locked in scrutiny:

- Reuse backtest engine via sweep scenario + new aggregator (no parallel computation path).
- Aggregator joins positions ← base_records on (date, match_id) to attach `open_interpretable_band`. Do NOT bake band into raw data — band depends on mutable settings.
- Sweep `drop_pct ∈ {10,20,...,95}` via existing `{"sweep": [...]}` mechanism.
- Filter games missing favorite tipoff price; report excluded count.
- Cell stats: recovery rate, N, Wilson 95% CI, median time-to-recovery, median further-drawdown.
- New dedicated page (do not extend `pages/scenario_results_page.py`).
- Distinct naming from `dip_recovery.py` to avoid confusion.

Design-mode additions (paths and surfaces; no implementation sequencing):

- **New files (proposed):**
  - `pages/nba_band_drop_recovery_page.py` — Dash page; class follows the `NBAOpenTipoffAnalysisPage` shape with `route = "/nba-band-drop-recovery"` and `title = "NBA Band Drop Recovery"`.
  - `backtest/scenarios/band_drop_recovery_sweep.json` — sweep scenario file containing the ten drop_pct buckets.
  - `band_drop_recovery.py` (top-level module, sibling to `dip_recovery.py`) — aggregator: takes engine positions DataFrame + base-records frame, returns the grid + per-bucket detail DataFrames. Reuses `_wilson_interval` from `nba_analysis.py`.
- **Modified files:**
  - `app.py` — register the new page in the route table.
  - `pages/nba_open_tipoff_page.py` — add a link from the band-reference panel to the new page (R19 / discoverability).
- **Scenario JSON shape (illustrative, finalized in spec):**
  ```json
  {
    "name": "band_drop_recovery_sweep",
    "universe_filter": {"name": "first_k_above", "params": {"k": 100, "min_price": 0.50}},
    "side_target": "favorite",
    "trigger": {
      "name": "pct_drop_window",
      "params": {
        "anchor": "tipoff",
        "drop_pct": {"sweep": [10, 20, 30, 40, 50, 60, 70, 80, 90, 95]}
      }
    },
    "exit": {"name": "reversion_to_open", "params": {}},
    "lock": {"mode": "sequential", "max_entries": 1, "cool_down_seconds": 0, "allow_re_arm_after_stop_loss": false},
    "fee_model": "taker"
  }
  ```
  Note: `fee_model` is required by `REQUIRED_KEYS` in `backtest/scenarios.py:13-21` but the aggregator discards PnL columns (R20).
- **Compatibility:** No changes to `analytics.py`, `dip_recovery.py`, or any existing scenario file. No schema migration. No cache invalidation required.
- **Route:** `/nba-band-drop-recovery`. No auth surface, no API exposure outside Dash.

Spec-mode additions (product-facing constraints; no implementation sequencing):

- **Pinned external dependencies (renaming/removing any of these is a breaking change for this page):**
  - `pct_drop_window` trigger and its support for `anchor="tipoff"`.
  - `reversion_to_open` exit and its `trigger.anchor_price` semantics.
  - `backtest/scenarios.py` `{"sweep": [...]}` expansion.
  - `INTERPRETABLE_BANDS` in `analytics.py` and the `open_interpretable_band` column in the base-records frame.
  - `_wilson_interval` in `nba_analysis.py`.
- **Default `min_n_display` = 5.** Exposed as a numeric input on the page.
- **Rollout:** v1 is additive (new page + new scenario file). No migration, no flag, no deprecation. Removable by deleting three files and reverting the link on the tipoff page.

## Repo grounding

### Captured by: probe @ 2026-05-16
- Files read: analytics.py, dip_recovery.py, nba_analysis.py, backtest/triggers/pct_drop_window.py, backtest/exits/reversion_to_open.py, backtest/scenarios.py, backtest/runner.py, backtest/scenarios/favorite_drop_50pct_60min_tp_sl.json, pages (directory listing)
- Key claims:
  - Interpretable bands defined at `analytics.py:91-98` as `INTERPRETABLE_BANDS` constant; five active bands plus Toss-Up.
  - `pct_drop_window` trigger (`backtest/triggers/pct_drop_window.py:22-85`) supports `anchor="tipoff"` and computes relative drop targets; first-touch via `hits.iloc[0]`.
  - `reversion_to_open` exit (`backtest/exits/reversion_to_open.py:15-41`) reverts to `trigger.anchor_price`, so with tipoff anchor it scans for first tick ≥ tipoff price.
  - Sweep expansion is generic (`backtest/scenarios.py:24-43`): any `{"sweep": [...]}` node fans out via `itertools.product`.
  - `dip_recovery.py` is for absolute-threshold micro-price intervals per-token — different problem from relative-to-tipoff favorite drops; not reusable without ~80% rewrite.
  - Base-records frame cached at `cache/_base_records/<settings_hash>.pkl` per CLAUDE.md; `open_interpretable_band` already materialized there for the join.
  - `_wilson_interval` helper exists in `nba_analysis.py`.
  - `pages/scenario_results_page.py` exists as prior art for rendering engine output but the 2D pivot shape justifies a new page.

### Captured by: intake @ 2026-05-16
- Files read: (reuses /probe grounding above — no additional reads required for problem/outcome/scope/actors framing)
- Key claims:
  - Problem framing comes from conversation, not from new repo reads; existing tipoff page surfaces unconditional rates but not the conditional-on-drop recovery rate.
  - Out-of-scope items chosen to match v1 of existing tipoff analysis surface (NBA only, favorite only, existing band definitions).

### Captured by: design @ 2026-05-16
- Files read: pages/nba_open_tipoff_page.py
- Key claims:
  - Existing tipoff page class shape (`pages/nba_open_tipoff_page.py:26-34`) — `route`/`title` class attrs, `__init__(analysis_service, settings)`, `layout(self)` — is the pattern to mirror for the new page.
  - `BAND_DEFINITIONS` is duplicated in `pages/nba_open_tipoff_page.py:16-23` separately from `analytics.py:91-98`. New page must source from `analytics.py` constant directly (R13/R14) rather than re-duplicating.
  - Filter controls on the tipoff page (`Price Quality`, `Minimum Open Favorite Price`, date pickers) are the parity baseline for the new page's filter UI (R19).

## Linking fields

- related_plans:
- related_tests:
- related_decisions:
- related_modules: analytics.py, backtest/triggers/pct_drop_window.py, backtest/exits/reversion_to_open.py, backtest/scenarios.py, backtest/runner.py, nba_analysis.py, pages/
- related_features:

## Changelog

- 2026-05-16: record created
- 2026-05-16: intake completed
- 2026-05-16: design completed
- 2026-05-16: spec completed
