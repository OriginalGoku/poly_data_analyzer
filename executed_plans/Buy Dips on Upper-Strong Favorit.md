# Buy Dips on Upper-Strong Favorites — Technical Plan (Final)

> Build a backtesting framework to test whether in-game dips in high-conviction favorites create better risk-adjusted entry points than buying at open, at tip-off, or at first in-game quote.

## Problem Statement

The plan proposes testing a **dip-buying timing strategy** for Upper Strong favorites (open price > 0.85). The goal is to determine whether waiting for in-game selloffs provides better entries than buying at open, accounting for execution costs and hold duration. This requires a structured backtest that measures multiple exit strategies, parameterized dip thresholds, and fee sensitivity—outcomes that existing analytics (dip_recovery, regime_transitions, discrepancy) don't directly provide.

## Codebase Context

**Key findings:**
- Game analytics already compute open/tipoff prices and interpretable bands using `analytics.py` (volume-thresholded VWAP after `pregame_min_cum_vol`)
- Trade-level in-game data is available with precise timestamps aligned to score events (`loaders.py`)
- Existing dip_recovery module detects absolute thresholds (under 5%, 4%, etc.) — different signal; don't reuse
- Settings are centralized (`ChartSettings`) and cached transparently
- Tests use synthetic fixtures and validate cache round-trip behavior
- Games are accessible via date-ordered scan of `data/YYYY-MM-DD/` directories
- Platform outages documented in `docs/POLY_OUTAGE_REPORT.md` — trade gaps and missing events are real

**Design decisions locked in after review:**
1. **Settlement:** Event-derived winners (final score from events) only; exclude event-missing games from settlement results. Separate `mark_to_market_at_gamma_close` metric for reference.
2. **Time-based exits:** Restrict to NBA games with events (v1). Use fixed NBA quarter durations (12 min per quarter). Multi-sport time exits deferred to v2.
3. **Open anchor:** Use `analytics.py` "meaningful open" (volume-thresholded VWAP after `pregame_min_cum_vol`). Aligns with existing quantile band definitions and infrastructure.

## Implementation Steps

### Step 1: Create backtest configuration and universe filter module
Files: `backtest_config.py`, `backtest_universe.py`
Depends on: none

**What changes:**
- `backtest_config.py` — New dataclass `DipBuyBacktestConfig` to hold strategy parameters: dip_thresholds (tuple of cents), exit_type (settlement/reversion/time_based), profit_target (cents), time_exit_checkpoint (quarter, or "off"), fee_model (taker/maker), sport_filter (nba/nhl/mlb/all)
- Add sport-specific config: `nba_quarter_duration_min = 12`, `nhl_period_duration_min = 20`, `mlb_inning_duration_min = None` (use wall-clock only)
- Document anchor choice: "Uses `analytics.py` meaningful_open (volume-thresholded VWAP after pregame_min_cum_vol); aligns with existing quantile bands; retrospective-only (knowable post-hoc)"
- Document settlement policy: "True settlement from event-derived winners; event-missing games excluded; separate `mark_to_market_at_gamma_close` metric provided for comparison"
- Fee model: hardcode Polymarket rates (`taker_fee_pct=0.002`, `maker_fee_pct=0.0`) — document as "Q1 2026 Polymarket fee schedule"
- `backtest_universe.py` — New module with `filter_upper_strong_universe(start_date, end_date, data_dir="data")` function that: loads game_analytics, filters to `open_favorite_price > 0.85` and `open_favorite_team != "Tie"`, returns qualified (date, match_id, sport, open_price, tipoff_price) tuples with settle-ability metadata

**Key details:**
- Config is immutable dataclass, mirrors parameter grid from plan section 8
- Universe filtering uses `analytics.load_game_analytics()` with date range support
- Output schema: `(date, match_id, sport, open_fav_price, tipoff_fav_price, open_fav_token_id, can_settle_from_events, price_quality)`
- Exclude games with `price_quality="inferred"` (optional config param; document rationale)

**Test strategy:**
- Unit: config construction with various dip threshold combos
- Unit: universe filter returns correct count of Upper Strong games for known date range
- Edge case: empty date range, no qualifying games, tie games (excluded), price_quality filters

---

### Step 2: Build trade-level entry/exit detection for dip buy signals
Files: `dip_entry_detection.py`
Depends on: Step 1 (uses config schema)

**What changes:**
- `dip_entry_detection.py` — New standalone module (does NOT reuse `dip_recovery`; different signal). Functions:
  - `find_dip_entry(trades_df, open_price, dip_threshold_cents, tipoff_time, game_end, settings)` — filters to in-game trades, finds first touch at or below `(open_price - dip_threshold_cents)`, returns entry time and entry price; or None if never triggered
  - `find_exit(trades_df, entry_time, entry_price, exit_type, exit_param, tipoff_time, game_end, sport, settings)` — detects multiple exit conditions:
    - `settlement`: final in-game trade (before game_end)
    - `reversion_to_open`: first trade >= open_price post-entry
    - `reversion_to_partial`: first trade >= (open_price - exit_param_cents) post-entry
    - `fixed_profit`: first trade >= (entry_price + exit_param_cents) post-entry
    - `time_based_quarter`: exit at scheduled quarter-end [NBA only in v1; config gates this]
  - Return schema: `{"entry_time": datetime, "entry_price": float, "exit_time": datetime | None, "exit_price": float | None, "exit_type": str, "hold_seconds": int, "status": "filled" | "not_triggered" | "time_based_not_applicable"}`

**Key details:**
- Entry uses "first touch only" rule — no repeated re-entries in same game (per plan section 3)
- Time-based exits:
  - NBA: use `settings.sport == "nba"` gate; compute quarter-end as `tipoff_time + (quarter_num * 12 minutes)`; require events to exist (to validate sport)
  - Other sports: mark as "time_based_not_applicable" (v1 limitation; document in results)
- Settlement exit: finds final in-game trade, not gamma-close trade (game_end is event-based, conservative boundary)
- Handle edge cases: entry signal never triggered (status="not_triggered"), exit condition never met (hold to game_end), entry in last trade before game end (minimal hold, valid trade)
- Store elapsed wall-clock time from entry (in minutes and seconds) for time-based exit analysis

**Test strategy:**
- Unit: synthetic trade sequence with known dip, verify entry detection at correct timestamp
- Unit: multiple exit types on same entry, verify correct exit prices
- Unit: time-based exit on NBA game (mock event schema), verify quarter-end calculation
- Edge case: dip below 0.01, shallow dip (1c), entry in last trade, no event (time_based skipped)

---

### Step 3: Compute settlement and PnL for each trade
Files: `backtest_settlement.py`, `backtest_pnl.py`
Depends on: Step 2 (uses entry/exit output)

**What changes:**
- `backtest_settlement.py` — New module with `resolve_settlement(manifest, events, trades_df, game_end, sport, settings)` that returns `(payout, resolved_method, settled)` where:
  - **Method 1 (event-derived):** If events exist and contain sufficient score data (final score determinable), compute winner via `loaders._derive_nba_final_winner()` [generalize for other sports] → payout = 1.0 if entry token wins, else 0.0
  - **Method 2 (trade-convergence):** If no events or missing winner, mark as `settled=False` (exclude from settlement-based results, don't fallback to trade price)
  - Return `(payout, method, settled)` tuple
  - Document: "Method 1 = true settlement; Method 2 = unresolved (excluded)"

- `backtest_pnl.py` — New module with `compute_trade_pnl(entry, exit, settlement, fee_model, settings)` that calculates:
  - Gross PnL: `(exit_price - entry_price) * 100` (in cents)
  - Fee cost: `exit_price * taker_fee_pct * 100` if fee_model=="taker", else 0
  - Net PnL: gross - fees
  - ROI: `net_pnl / (entry_price * 100)`
  - Hold duration: from entry_time to exit_time (in minutes and seconds)
  - True PnL (if settled): `(settlement_payout - entry_price) * 100` (hold entire position)
  - MAE/MFE: max adverse and favorable excursion from entry to exit (in cents)
  - Trade-quality metrics: settlement_method, settlement_occurred, mark_to_market_price_at_gamma_close
  - Return schema: all above fields as a dict

**Key details:**
- Fees: use config values (`taker_fee_pct=0.002`, `maker_fee_pct=0.0`)
- MAE/MFE computed from trade data post-entry to exit time (query trades between entry and exit, find min/max)
- Mark-to-market: compute as "last trade price at or before gamma_closed_time" (separate from settlement); document as "reference only, stale post-outage"
- Settlement: only compute if `settled=True` from resolver; else skip true-PnL calculation

**Test strategy:**
- Unit: 2-cent profit with taker fee, verify net PnL is positive
- Unit: 5-cent loss should remain negative even before fees
- Unit: settlement resolver returns payout=1.0 for winning team entry
- Edge case: zero-width entry/exit (entry == exit), settlement_occurred=False

---

### Step 4: Build baseline computation for buy-at-open and buy-at-tip strategies
Files: `backtest_baselines.py`
Depends on: Step 1, Step 3 (imports universe, settlement, pnl modules)

**What changes:**
- `backtest_baselines.py` — New module with three functions:
  - `baseline_buy_at_open(open_price, trades_df, tipoff_time, game_end, manifest, events, sport, settings)` — entry at open_price, exit at settlement (final in-game trade before game_end), compute PnL via Steps 3
  - `baseline_buy_at_tipoff(tipoff_price, trades_df, tipoff_time, game_end, manifest, events, sport, settings)` — entry at tipoff_price, exit at settlement
  - `baseline_buy_first_ingame(trades_df, tipoff_time, game_end, manifest, events, sport, settings)` — entry at first in-game trade, exit at settlement
- Each returns same PnL dict as Step 3 (for consistency)

**Key details:**
- Settlement for baselines: always "hold to settlement" (use settlement_resolver from Step 3)
- Settlement = final in-game trade before game_end, or event-derived payout if available
- Handle no-trade edge case (gracefully mark as "no_data", skip from aggregation)
- Reuse `compute_trade_pnl()` from Step 3 for consistency

**Test strategy:**
- Unit: baseline vs strategy on same game, verify baseline PnL computed correctly
- Unit: all three baselines produce output for same game
- Edge case: game with no in-game trades (should skip)

---

### Step 5: Create backtest execution engine for single game
Files: `backtest_single_game.py`
Depends on: Step 2, Step 3, Step 4

**What changes:**
- `backtest_single_game.py` — New module with `backtest_single_game(date, match_id, config, data_dir="data")` that:
  - Loads game via `loaders.load_game()` (trades_df, events, manifest)
  - Loads analytics snapshot via `analytics.get_analytics_view()` to get open/tipoff prices, band info
  - Filters by dip threshold, finds entry/exit via Step 2
  - Computes PnL via Step 3
  - Computes all three baselines via Step 4
  - Returns one row dict with all metrics

- Return schema: one row dict with columns:
  ```
  strategy | dip_threshold | exit_type | fee_model | sport | match_id | date |
  trades | entry_price | exit_price | gross_pnl_cents | net_pnl_cents | roi_pct |
  hold_minutes | max_adverse_excursion | max_favorable_excursion |
  settlement_method | settlement_occurred | true_pnl_cents (if settled) |
  baseline_buy_at_open_roi | baseline_buy_at_tip_roi | baseline_buy_first_ingame_roi |
  mark_to_market_at_gamma_close | status
  ```

**Key details:**
- Single game → single trade (one dip entry/exit per game), or no trade if entry not triggered
- Config parameterizes everything: dip_threshold, exit_type, fee_model
- Reuse analytics.py infrastructure to get open/tipoff prices (no re-computation)
- Error handling: gracefully skip if game missing critical data (events for settlement, trades for entry/exit, or open_price unavailable)
- Status field: "filled" | "not_triggered" | "settled" | "missing_events" | "missing_trades"

**Test strategy:**
- Unit: synthetic game with known open, dip, and settlement prices; verify one row output with correct ROI
- Integration: real game from cache, verify all columns populated and baselines > 0 (for strong favorites)
- Edge case: game where dip entry never triggered, game missing events, game missing in-game trades

---

### Step 6: Build results aggregation and grid testing
Files: `backtest_runner.py`
Depends on: Step 5

**What changes:**
- `backtest_runner.py` — New module with `run_backtest_grid(start_date, end_date, configs, data_dir="data")` that:
  - Iterates universe (date range filtered to Upper Strong, via Step 1)
  - For each (date, match_id) × config combo: runs `backtest_single_game()`
  - Accumulates results into single DataFrame
  - Computes per-strategy aggregations: total trades, mean ROI (unweighted), win_rate (resolved_yes / total_settled), avg hold time, percentile max_dd
  - Returns aggregated DataFrame (one row per strategy combo)

- Aggregation schema (one row per strategy):
  ```
  strategy | dip_threshold | exit_type | fee_model | sport_filter |
  total_games_in_universe | games_with_entry | games_settled |
  total_trades | gross_roi_mean | net_roi_mean | win_rate |
  avg_entry_price | avg_hold_minutes | percentile_95_max_adverse_excursion |
  settlement_method_dist | games_excluded_reason_dist | status
  ```

**Key details:**
- Outer loop: (dip_threshold, exit_type, fee_model, sport_filter) configs
- Inner loop: all (date, match_id) in universe
- Aggregation: count trades, mean ROI (unweighted per trade; or weighted by notional? → unweighted for v1 simplicity), compute win_rate only on games_settled
- Filter stats: total games in date range, games with open_fav_price (filtered), games in Upper Strong band, games with settable winner from events
- Exclusion tracking: count games skipped per reason (missing events, missing trades, no entry triggered, etc.)

**Test strategy:**
- Unit: mock config grid (2 dips × 2 exits × 2 fee models), verify output shape (8 rows if all tested)
- Integration: small date range (1 week), verify output and column names
- Spot-check: manual calculation of one row's ROI from individual trades

---

### Step 7: Implement results export and visualization
Files: `backtest_export.py`
Depends on: Step 6

**What changes:**
- `backtest_export.py` — New module with `export_backtest_results(results_df, single_game_df, output_dir, config)` that:
  - Writes `results_aggregated.csv` and `results_aggregated.json` (per-strategy summary)
  - Writes `results_per_game.csv` and `results_per_game.json` (all single-game records)
  - Generates `BACKTEST_SUMMARY.txt` with:
    - Date range, total games tested, filter stats
    - Key findings (best/worst performers by ROI and win_rate)
    - Settlement method distribution
    - Exclusion counts by reason
  - Generates simple Plotly figure (if applicable): ROI heatmap (dip_threshold × exit_type, faceted by fee_model)
  - Document schema in output folder (markdown file listing all columns and definitions)

**Key details:**
- CSV/JSON: human-readable and machine-parseable
- Summary: markdown format, suitable for inclusion in wiki/retrospective
- Plots: one per fee_model (taker/maker); x-axis dip_threshold, y-axis exit_type, color = net_roi
- Schema doc: for reproducibility, list column definitions and aggregation formulas

**Test strategy:**
- Unit: tiny results_df (3 rows), verify CSV/JSON write and round-trip load
- Integration: export from Step 6 results, verify human-readable table and plots generate

---

### Step 8: Add backtest CLI entry point and comprehensive tests
Files: `tests/test_backtest_*.py`, new `backtest_cli.py` (optional)
Depends on: Step 7

**What changes:**
- `tests/test_backtest_config.py` — Unit tests for config creation, dip threshold parsing, fee model validation
- `tests/test_backtest_universe.py` — Unit tests for upper-strong filtering, edge cases (ties, missing prices)
- `tests/test_dip_entry_detection.py` — Unit tests for entry/exit detection with synthetic trades; test all exit types
- `tests/test_backtest_settlement.py` — Unit tests for settlement resolver (event-derived, unresolved cases)
- `tests/test_backtest_pnl.py` — Unit tests for PnL calculation, fee handling, MAE/MFE, edge cases
- `tests/test_backtest_single_game.py` — Integration test on synthetic full game (entry → exit → settlement)
- `tests/test_backtest_runner.py` — Integration test on tiny universe (2-3 games), verify aggregation
- `backtest_cli.py` (optional) — CLI entry point:
  ```
  python backtest_cli.py --start-date 2026-03-01 --end-date 2026-04-01 \
    --dip-thresholds 10,15,20 --exit-types settlement,reversion_to_open \
    --fee-models taker,maker --sport nba --output results/
  ```

**Key details:**
- Use existing test fixtures from `test_dip_regime.py` (_base_time, _manifest, _trade_rows, _events)
- Mock `loaders.load_game()` and `analytics.get_analytics_view()` to return synthetic data for deterministic testing
- Full integration test: construct synthetic game with known open, dip, and resolution; verify end-to-end PnL
- CLI wraps `run_backtest_grid()` and `export_backtest_results()`

**Test strategy:**
- Unit: each module tested independently with synthetic data
- Integration: end-to-end from CLI to CSV export
- Regression: verify results stable across code changes

---

## Execution Preview

```
Wave 0 (5 parallel):
  Step 1 — Backtest config, universe filter, and settlement policy documentation
  Step 2 — Dip entry/exit detection (standalone, not reusing dip_recovery)
  Step 3 — Settlement resolver and PnL computation
  Step 4 — Baseline strategy implementations
  Step 7 — Results export and visualization

Wave 1 (1 sequential):
  Step 5 — Single-game backtest execution (depends on Step 2, 3, 4)

Wave 2 (1 sequential):
  Step 6 — Results aggregation and grid testing (depends on Step 5)

Wave 3 (1 sequential):
  Step 8 — Tests and CLI entry point (depends on Step 1-7)

Critical path: Step 1 → Step 2 → Step 5 → Step 6 → Step 8 (5 waves)
Max parallelism: 5 agents (Wave 0)
```

## Risk Flags

- **Settlement edge cases:** Event-missing games (NBA CDN 403s, incomplete MLB/NHL) are excluded from settlement-based results; document count in summary. Trade-convergence used only as separate mark-to-market reference (not settlement proxy).
- **Time-based exits (v1 scope):** Restricted to NBA games with events. Other sports/missing events marked as "not_applicable". Multi-sport time exits deferred to v2 after v1 results.
- **Open anchor policy:** Using `analytics.py` "meaningful open" (volume-thresholded, retrospective). Aligns with existing infrastructure but requires `pregame_min_cum_vol` parameter matching. Document in config as "volume-conditional; known post-hoc."
- **Favorite token lock-in:** Dip entry binds to original open-favorite token; never re-selects if prices flip. Keep strategy definition simple for v1; revisit in v2 if needed.
- **Fee assumptions:** Hardcoded Polymarket Q1 2026 rates (0.2% taker, 0% maker). Document clearly; update if rates change.
- **File overlap:** Steps 2 and 4 both filter trades to in-game windows — factor trade-filtering utility into Step 2 to avoid duplication.

## Verification Checklist

After all steps complete:

1. **Unit tests:** `python -m pytest tests/test_backtest_*.py -v` — all pass
2. **Integration test:** Synthetic game with known outcome computes correct ROI end-to-end
3. **Small backtest:** Run on 1-week sample (e.g., 2026-03-23 to 2026-03-30); verify output table shape and column names
4. **Settlement stats:** Backtest summary reports how many games settled by method (events, unresolved), how many excluded per reason
5. **Baseline sanity check:** Buy-at-open ROI should be > 0 for Upper Strong favorites (if market efficient)
6. **Fee impact:** Net ROI (after taker fees) should be close to gross ROI minus ~0.4% (entry + exit fees)
7. **Reproducibility:** Export includes config, date range, and schema doc; results reproducible from same date range + code version

## Key Design Decisions (Locked In)

1. **Settlement = event-derived winners only.** Event-missing games excluded from settlement-based results. Separate `mark_to_market_at_gamma_close` metric provided (reference only, may be stale post-outage).

2. **Time-based exits = NBA games with events, v1 only.** Use fixed NBA quarter durations (12 min per quarter). Multi-sport deferred to v2.

3. **Open anchor = `analytics.py` "meaningful open".** Volume-thresholded VWAP after `pregame_min_cum_vol`, aligns with existing quantile band definitions, retrospective-only.

4. **Dip definition = standalone module.** Independent of existing `dip_recovery` (different signal: favorite drawdown from anchor, not absolute threshold). New `dip_entry_detection.py` module.

5. **Fee model = hardcoded Poly rates.** Taker: 0.2%, Maker: 0%. Document as Q1 2026 baseline; parameterizable for sensitivity if needed.

---

## Summary

This backtest framework will answer: **"Do dips in upper-strong favorites create better risk-adjusted entries than buying at open, and does the edge survive taker fees?"**

The plan separates concerns cleanly (config → universe filter → entry/exit → settlement → PnL → aggregation → export), handles data limitations gracefully (event-missing games, trade gaps from outages), and documents all assumptions for reproducibility.
