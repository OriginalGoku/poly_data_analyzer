# Plans Index
<!-- Auto-maintained by /save-plan. Do not edit manually. -->

## [plan_file: NBA_Game_Visualizer_Plan.md] 2026-04-08
**Summary:** Dash+Plotly single-game viewer for NBA Polymarket trade data with game event overlays and key market timestamps.
**Key decisions:**
- Dash+Plotly over Streamlit for richer chart interactivity and synced zoom
- NBA-only, single game view (NHL/MLB and multi-game deferred)
- No bid/ask spread visualization — focus on executed trade data as-is
- First event `time_actual` as tip-off anchor (more accurate than `gamma_start_time`)

---

## [plan_file: Whale_Tracker_Plan.md] 2026-04-10
**Summary:** Add whale wallet identification, classification (Market Maker / Directional / Hybrid), and visualization to the NBA game viewer.
**Key decisions:**
- Side attribution is taker-only — buy/sell direction only meaningful for the trade aggressor
- Scatter line overlay instead of bar overlay to avoid barmode="stack" conflict
- Two separate leaderboards (Aggressors + Liquidity) instead of one blended list
- Volume denominator is single-counted trade volume for intuitive percentages

---

## [plan_file: Price_Sensitivity_Plan.md] 2026-04-11
**Summary:** Compute per-event price reactions to scoring plays and visualize as a timeline scatter and binned sensitivity surface, with per-game disk caching.
**Key decisions:**
- Cache in local `cache/` directory, not game data folder (data/ is a symlink to upstream)
- VWAP of 5 trades before/after each event (configurable), not simple mean
- 3 lead bins (Close 0-5, Moderate 6-12, Blowout 13+) with configurable thresholds
- Both quarter-based and time-based (6-min buckets) phase views in sensitivity surface

---

## [plan_file: Backtest_Correctness_Fixes_Plan.md] 2026-04-14
**Summary:** Fix six confirmed bugs in the backtest engine: look-ahead bias in exits, zero-PnL silent losses, one-sided fee, gross/net ROI confusion, broken time_based_quarter (removed), and baseline fee model mismatch.
**Key decisions:**
- Not-triggered exits use forced-close at last in-game price (not excluded from ROI mean)
- time_based_quarter removed entirely (three compounding bugs, no active users)
- Two-sided fee: (entry_price + exit_price) * fee_pct applied in compute_trade_pnl()
- Baselines inherit fee_model from config instead of hardcoding "taker"

---

## [plan_file: Backtest_Engine_Redesign_Technical_Plan.md] 2026-04-25
**Summary:** Rip-and-replace the dip-buy backtester with a generic, JSON-scenario-driven engine where universe filters, triggers, and exits are independently registered components and scale-in (multi-position) per game is first-class.
**Key decisions:**
- Three per-stage registries (UNIVERSE_FILTERS / TRIGGERS / EXITS); no monolithic Strategy class
- Scale-in is first-class via PositionManager with sequential and scale_in lock modes
- Every Exit has a real exit_time; no-fill cases force-close at game_end with status="forced_close"
- Scenario JSON with `{"sweep": [...]}` leaves expanded into Cartesian concrete scenarios; one row per Position in output

---

## [plan_file: Scenario_Runner_Live_Progress_Plan.md] 2026-05-01
**Summary:** Surface per-game progress on the `/scenario-runner` page so the UI no longer appears frozen during a run.
**Key decisions:**
- Per-game counter + current-item label (no log tail)
- Bar resets per scenario; header carries `Scenario k/N`
- Extend `progress_callback` arity to `(scen_done, scen_total, game_done, game_total, msg)` rather than add a new channel
- Emit "loading universe" signal before the inner game loop to cover slow-filter cases

---

## [plan_file: NBA_Tipoff_Page_Performance_Plan/] 2026-05-15
**Summary:** Speed up `/nba-open-tipoff-analysis` (currently ~5min for 99 date dirs) via persistent per-game disk cache, eliminating trades.json.gz double-read, repo-wide base cache, and removing the price-quality date-reset retrigger.
**Key decisions:**
- Persistent disk cache mirroring `sensitivity.py` / `dip_recovery.py` idiom (per-game JSON with schema_version + settings_hash)
- Eliminate double gzip+JSON load by threading `loaders.load_game` output through the detail loop
- Drop date-range from `_load_game_analytics_cached` key so overlapping ranges share work
- Defer parallelism (ProcessPoolExecutor) until after caching + double-read fix — explicit user direction
- Decouple `populate_dates` from `nba-analysis-price-quality` to stop silent retriggers

---

## [plan_file: features/statistical-odd-analyzer/technical-plan.md] 2026-05-16
**Summary:** New Dash page `/nba-band-drop-recovery` showing a 2D grid (open band × drop magnitude) of P(price recovers to tipoff | first-touched X% drop), via sweep of the existing backtest engine.
**Key decisions:**
- Reuse `pct_drop_window` (anchor=tipoff) + `reversion_to_open` exit via a single sweep scenario; no parallel price-scanning code.
- Sweep `drop_pct ∈ {10..95}`; cumulative buckets fall out of independent scenarios.
- Aggregator joins engine positions ← cached base-records frame on (date, match_id) to attach `open_interpretable_band`; bands never recomputed.
- Cell stats: recovery rate, N, Wilson 95% CI, median time-to-recovery, median further-drawdown; PnL/fee columns discarded.
- Additive only — no changes to analytics, engine, or existing scenario files.

---

## [plan_file: Pregame_Volume_Filter_Plan/] 2026-05-16
**Summary:** Add a hard pregame-volume gate to the main dashboard game-picker (driven by existing `pregame_min_cum_vol`) plus a soft `data_warning_min_pregame_vol` badge on the game-card to surface truncated trade data.
**Key decisions:**
- Reuse single `pregame_min_cum_vol` knob as both open-anchor threshold and game-list hard gate (no second knob)
- Add separate soft threshold `data_warning_min_pregame_vol = 20000` for visible warning badge
- Signal: `pre_game_notional_usdc` primary; badge also looks at `trade_count` (hardcoded < 50)
- Gate applied as post-cache row mask in `get_analytics_view` (mirrors `start_date`/`end_date` pattern) — no new cache key

---
