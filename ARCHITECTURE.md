# Architecture

## Overview

Single-page Dash application that loads Polymarket trade data from disk and renders interactive Plotly charts plus per-game regime analytics. Current UI supports NBA, NHL, and MLB in a single-game view, with analytics computed from cross-game checkpoint data within the active sport and price-quality slice. The single-game view now also computes discrepancy forward returns, favorite-side band transitions, and absolute dip recovery intervals from in-game trade sequences.

## Components

### `loaders.py` -- Data Loading

- Scans `data/` for date directories, loads `manifest.json`, filters to collected NBA games
- `load_game()` loads gzip-compressed trades/events files into a pandas DataFrame, parses events, builds tricode-to-team mapping by tracking score changes, parses gamma timestamps. Heavy parsing factored into `build_loaded_game(data_dir, date, manifest, trades_data, outlier_settings)` so streaming callers can supply already-decompressed trades data and avoid a second disk read.
- `_read_json()` helper auto-detects `.gz` suffix for transparent gzip/plain JSON reading
- Returns a dict with manifest, trades DataFrame, events list, tricode map, and parsed timestamps

### `analytics.py` -- Game-Level Regime Analytics

- Scans all collected trade files and extracts only checkpoint headers needed for cross-game analysis
- Computes per-game favorite-side snapshots for:
  - market open (short post-threshold pregame VWAP/median window after cumulative pregame volume reaches `pregame_min_cum_vol`)
  - tip-off (`last_pregame_trade_price`)
- Assigns interpretable favorite-strength bands:
  - `Toss-Up`
  - `Lean Favorite`
  - `Lower Moderate`
  - `Upper Moderate`
  - `Lower Strong`
  - `Upper Strong`
- Computes sport-specific quantile cutoffs and quantile bands (`Q1`, `Q2`, `Q3`)
- Supports `price_quality` filtered comparison populations (`all`, `exact`, `inferred`)
- NBA analysis can drop ultra-tight opens using `analysis_min_open_favorite_price`, and reports how many games were excluded by that rule
- Exposes cached analytics records used by the UI controls and the game analytics card
- Equal favorite-side prices are represented as `Tie` rather than defaulting to token order
- `stream_game_analytics(...)` yields `(base_record, get_game)` per game, letting bulk pipelines (NBA tipoff) read each `trades.json.gz` exactly once while keeping RAM at one game at a time. The base-records frame persists across Dash restarts at `cache/_base_records/<settings_hash>.pkl` with a sidecar `<settings_hash>.manifest.json` recording each game's `input_fingerprint`; mismatched or new entries are rescanned, the rest hydrate from disk.
- `get_analytics_view` cache key no longer includes `start_date`/`end_date`. The date filter is applied on `view` between the sport filter and the `quantile_source = view` assignment so quantile bands remain window-local; subsequent ranges in the same process are free.

### `nba_tipoff_cache.py` -- NBA Tipoff Detail-Row Disk Cache

- Persistent per-game cache for the `/nba-open-tipoff-analysis` detail rows
- Path: `cache/<date>/<match_id>_nba_tipoff.json`
- Payload: `{schema_version, settings_hash, input_fingerprint, row}`
- `settings_hash` hashes the ChartSettings fields that influence the row (`pregame_min_cum_vol`, `vol_spike_std`, `vol_spike_lookback`, `post_game_buffer_min`, open-favorite team/price)
- `input_fingerprint` hashes `(mtime_ns, size)` for the trades/manifest/events files; catches re-collected raw data. Unique to this cache among per-game caches because it backs the user-visible perf path.
- `load_or_compute_nba_tipoff_detail(...)` accepts either an eager `game` dict or a lazy `game_provider` callable; cache hits skip the game load entirely.

### `charts.py` -- Chart Building

- `build_charts()` builds two subplot figures:
  - **Pre-game:** 3-row shared-x-axis figure
  - **In-game:** 4-row shared-x-axis figure when top taker whales are present
- Shared rows:
  - **Row 1 (55%):** Price lines for both tokens, vertical reference lines (scheduled start, tip-off, market close), scoring event markers, and top-10 taker whale trade markers
  - **Row 2 (25%):** Stacked BUY/SELL volume bars (1-min or 5-min buckets), volume spike markers, and team-specific taker whale overlays such as `{Team} Whale Buy` / `{Team} Whale Sell`
  - **Row 3 (20%):** Cumulative volume line with rangeslider
- In-game only:
  - **Row 4:** Top aggressor cumulative-dollar panel, split by ranked whale, team, and taker direction
- Uses `Scattergl` (WebGL) for price lines to handle 10K+ trade datasets
- Event markers placed at nearest trade price (within 60s) or last known price
- Whale trade markers on Row 1 are filtered by `whale_marker_min_trade_pct` to suppress tiny fills
- Whale volume overlays on Row 2 are directional and taker-only; maker flow is intentionally excluded because side is not inferable
- Additional single-game figures:
  - `build_discrepancy_intervals_chart()` renders market-score discrepancy spans with forward-return hover metrics
  - `build_regime_transitions_chart()` groups confirmed favorite-side band transitions into quarter/time-bucket summaries
  - `build_dip_recovery_chart()` groups absolute threshold dip recoveries by quarter and time bucket

### `sensitivity.py` -- Event Sensitivity

- Computes per-scoring-event price sensitivity using the away token only
- Measures VWAP before and after each scoring event using the last `sensitivity_price_window_trades` fills before the event and the first `sensitivity_price_window_trades` fills after it
- Derives `pre_lead`, `post_lead`, `lead_bin`, and `time_bin` for each scoring play
- Caches computed rows to `cache/{date}/{match_id}_sensitivity.json` so repeated dashboard views do not recompute the same game
- Supplies the row-level data used by the sensitivity timeline scatter and the quarter/time-bucket surface summaries

### `discrepancy.py` -- Market-Score Discrepancies

- Detects intervals where the scoreboard leader and the market favorite disagree, or where tied games trade outside the dead zone
- Computes interval-level opportunity metrics (`avg_discrepancy`, `max_improvement`, `flip_flag`) plus forward-return metrics measured from the interval start over a configurable horizon
- Caches rows to `cache/{date}/{match_id}_discrepancies.json`

### `regime_transitions.py` -- Favorite-Side Band Transitions

- Works from favorite-side probabilities only, per the project convention for regime analytics
- Detects confirmed transitions between interpretable bands after a configurable number of confirming trades
- Stores period, time bucket, transition direction, forward max/min price, and low-confidence flags for sparse windows or large gaps
- Caches rows to `cache/{date}/{match_id}_regime_transitions.json`

### `dip_recovery.py` -- Absolute Threshold Dip Recovery

- Scans both team tokens during in-game trading windows for dips below configured absolute thresholds
- Builds contiguous below-threshold intervals, tracks minimum price, recovery magnitude, and whether the interval recovered, remained below, or ended with the game
- Caches rows to `cache/{date}/{match_id}_dip_recovery.json`

## Backtest Framework

Two engines coexist: the legacy dip-buy framework (described first) and a newer generic scenario-driven engine (see "New Scenario-Driven Backtest Engine" below). The legacy engine is wired up in parallel and slated for removal in Step 19 after a 2-week gating period.

### Legacy: Dip-Buy Framework

Complete dip-buy backtesting system for evaluating entry and exit strategies on historical Polymarket sports trade data.

### Entry Points & Configuration

#### `backtest_cli.py` -- CLI Entry Point
- Parses command-line arguments: date range, dip thresholds, exit types, fee models, sport filter
- Instantiates `DipBuyBacktestConfig` objects for each exit-type/fee-model combination
- Delegates grid execution to `run_backtest_grid()`

#### `backtest_config.py` -- Configuration
- `DipBuyBacktestConfig`: Frozen dataclass with:
  - **Dip thresholds**: Tuple of dip amounts in cents (e.g., 10, 15, 20 cents below market open)
  - **Exit types**: `settlement` (hold to market close), `reversion_to_open` (exit when price returns to open), `reversion_to_partial` (exit at open + profit_target), `fixed_profit` (exit at open + fixed cents)
  - **Fee models**: `taker` (0.2% Polymarket fee) or `maker` (0% fee)
  - **Sport filter**: `nba`, `nhl`, `mlb`, or `all`
  - Validation in `__post_init__` ensures non-empty thresholds, valid parameters

### Grid Orchestration & Aggregation

#### `backtest_runner.py` -- Grid Orchestration
- `run_backtest_grid()`: For each date in the range, loads all games matching sport and quality filters, runs each config on each game
- Collects per-game results, aggregates across all games per config
- Returns `aggregated_df` (one row per config with statistics) and `per_game_df` (all trade-level records)

#### `backtest_universe.py` -- Universe Filtering
- `filter_upper_strong_universe()`: Filters to games where market open indicated upper-strong favorite (above 75th percentile)
- Used when testing strategies on a restricted population

### Single-Game Execution

#### `backtest_single_game.py` -- Single-Game Orchestration
- Orchestrates entry detection, exit logic, and PnL computation for one game + one config
- Calls `find_dip_entry()` to locate the dip touch
- Applies config's exit type logic (e.g., find reversion price, fixed profit target)
- `find_exit()` bounds post-entry search to `< game_end` to prevent post-settlement price spikes; non-settlement exits that never hit their target return `forced_close` (last in-game price) instead of zero PnL
- Computes settlement price from events
- Returns trade record with entry price, exit price, PnL, win/loss, holding duration

### Strategy & Entry/Exit Logic

#### `backtest_baselines.py` -- Baseline Strategies
- `baseline_buy_at_open()`: Buys at market-open price (from pre-game VWAP), exits per config
- `baseline_buy_at_tipoff()`: Buys at first tipoff-time trade, exits per config
- `baseline_buy_first_in_game()`: Buys at first in-game trade, exits per config
- Each accepts a `fee_model` parameter (instead of hardcoding `"taker"`) and returns PnL record with entry/exit prices and fees applied

#### `dip_entry_detection.py` -- Dip Touch Detection
- `find_dip_entry()`: Scans in-game trades (post-tipoff), finds first touch at or below (open_price - dip_threshold_cents / 100)
- Returns entry dict with price, timestamp, or None if no dip
- Respects in-game window (tipoff to game_end)

### Settlement & PnL

#### `backtest_settlement.py` -- Settlement Resolution
- `resolve_settlement()`: Extracts final settlement price from events or trade data
- Handles market close timing, outcome state, and edge cases (overtime, data gaps)
- Returns settlement price and resolution metadata

#### `backtest_pnl.py` -- Trade-Level PnL
- `compute_trade_pnl()`: Given entry, exit, and fee_pct, calculates PnL in cents and %
- Charges two-sided fee `(entry_price + exit_price) * fee_pct * 100`, matching Polymarket's model
- `gross_roi_mean` in aggregation uses `gross_pnl_cents / (entry_price * 100)` (not `roi_pct`, which is net)
- Returns PnL, win/loss flag, and holding duration

### Results Export & Visualization

#### `backtest_export.py` -- Export & Visualization
- `export_backtest_results()`: Exports aggregated results (one row per strategy) and per-game records
  - **CSV exports**: `aggregated.csv` (strategy summary) and `per_game.csv` (all trade records)
  - **JSON exports**: Same data as JSON for programmatic analysis
  - **Heatmap visualization**: Dip threshold (rows) vs exit type (columns), colored by return %; separate heatmaps for each fee model and sport
- Visualizations use Plotly subplots with sorted rows/columns for readability

## New Scenario-Driven Backtest Engine

Generic, JSON-scenario-driven backtester running parallel to the legacy framework. Components are pluggable and decorator-registered; scenarios compose from `universe_filter` + `triggers` + `exits` specs.

### Contracts (`backtest/contracts.py`)

Frozen dataclasses defining the public surface:
- `Context` -- per-game evaluation state passed to filters/triggers/exits
- `Trigger`, `Exit` -- abstract bases each component implements
- `Position` -- entry record with side, anchor, fees applied
- `LockSpec` -- locking policy for the `PositionManager`; `mode = "sequential" | "scale_in"`
- `ComponentSpec` -- `{name, params}` reference resolved against a registry
- `Scenario` -- top-level scenario: `name`, `side_target` (`"favorite" | "underdog"`), `universe_filter`, `triggers`, `exits`, `lock`, `sport`, fee model
- `GameMeta` -- summary fields used by filters and aggregation

### Registry (`backtest/registry.py`)

Three name -> class registries: `UNIVERSE_FILTERS`, `TRIGGERS`, `EXITS`. Components register themselves at import time via decorator.

### Components

- `backtest/filters/` -- universe filters (`upper_strong.py`, `first_k_above.py`)
- `backtest/triggers/` -- entry triggers (`dip_below_anchor.py`, `pct_drop_window.py`)
- `backtest/exits/` -- exits (`settlement.py`, `reversion_to_open.py`, `reversion_to_partial.py`, `fixed_profit.py`, `tp_sl.py`)

### Scenario Loader (`backtest/scenarios.py`)

- Reads JSON scenario definitions from `backtest/scenarios/*.json`
- Supports parameter sweeps: a list under any `params` key fans out into the cartesian product of `Scenario` instances
- Returns a flat list of fully-resolved `Scenario` objects

### Position Manager (`backtest/position_manager.py`)

Owns open positions and applies the scenario's `LockSpec`:
- `sequential` -- only one open position at a time per scenario; new triggers ignored while locked
- `scale_in` -- multiple concurrent positions allowed up to a configured cap

### Engine (`backtest/engine.py`)

Per-game loop:
1. Apply `universe_filter` against `GameMeta`; skip if rejected
2. Walk in-game trades chronologically, evaluating triggers
3. On trigger fire, open `Position` via `PositionManager`
4. Each tick, evaluate active exits per position
5. At `game_end`, call `pm.tick(ctx, game_end)` one final time so scanner-driven exits (e.g., `reversion_to_open`) see the full trade tape before any remaining open positions are force-closed and tagged with `forced_close`. Skipping the final tick used to cause sequential-lock + scanner-driven exits to never fire on the last in-game tape segment.

### Runner (`backtest/runner.py`)

- Loads games over `[start_date, end_date]` using existing loaders
- Runs each `Scenario` through `engine.run_game(...)` for every game
- Returns:
  - per-position DataFrame (one row per closed position, all metadata)
  - aggregation DataFrame (one row per scenario; counts, mean ROI, win rate, etc.)
- CLI flags: `--scenario`, `--scenarios-glob`, `--start-date`, `--end-date`, `--data-dir`, `--output`

### UI

- `pages/scenario_builder_page.py` -- `/scenario-builder`; guided form that picks filter/trigger/exit/lock/fee_model, renders typed param inputs from each component's `PARAM_SCHEMA`, supports per-field sweep toggles, previews and saves to `backtest/scenarios/<slug>.json`
- `pages/scenario_runner_page.py` -- `/scenario-runner`; pick a scenario JSON, set date range, kick off a run
- `pages/scenario_results_page.py` -- `/scenario-results`; browse aggregated results and per-position records produced by the runner
- `pages/nba_band_drop_recovery_page.py` -- `/nba-band-drop-recovery`; owns its own engine invocation against the `band_drop_recovery_sweep` scenario and renders a 2D grid (rows = open interpretable bands, columns = drop-pct buckets) of conditional recovery base rates with Wilson 95% CIs. Aggregation logic lives in `band_drop_recovery.py`, which joins the runner's per-position DataFrame against the cached base-records frame.

Each registered component module declares a `PARAM_SCHEMA = [...]` constant (typed entries: `int | float | bool | enum | int_pair | nullable_int`; sweepable fields opt in via `"sweepable": True`). The subpackage `__init__.py` registers the schema in `UNIVERSE_FILTER_SCHEMAS` / `TRIGGER_SCHEMAS` / `EXIT_SCHEMAS` next to the callable so the builder UI renders inputs without duplicating schemas.

### `whales.py` -- Whale Analysis

- `analyze_whales()` identifies high-volume wallets exceeding a configurable % of total market volume
- Classification based on maker/taker ratio: **Market Maker** (high maker %, 20+ trades), **Directional** (high taker %), **Hybrid** (mixed)
- Side attribution uses taker trades only (BUY/SELL/Mixed)
- Per-wallet stats include maker and taker trade-size summaries: count, min, max, mean, median
- `get_whale_trades()` filters a trades DataFrame to only trades involving whale addresses
- Settings: `whale_min_volume_pct` (threshold), `whale_max_count` (cap), `whale_maker_threshold_pct` (classification boundary), `whale_marker_min_trade_pct` (minimum plotted whale trade size as % of game volume)

### `app.py` -- Dash Application

- Layout: dark theme, sport/date/game/price-quality controls, info cards (game metadata, pre-game summary, game analytics, chart settings), whale tracker card, sensitivity charts, discrepancy chart, regime transition chart, dip recovery chart, and the pre-game/in-game figures
- Whale tracker card renders separate full-width aggressor and maker sections rather than a shared two-column layout
- Three callbacks:
  1. Populate sport dropdown from cached analytics records
  2. Populate date and game dropdowns from the active sport / price-quality slice
  3. Load the selected game, run whale analysis, derive the top-10 non-maker taker whales, compute/load sensitivity, discrepancy, regime-transition, and dip-recovery caches, then build charts and populate metadata / pre-game / analytics / whale cards

## Data Flow

```
data/YYYY-MM-DD/manifest.json
        |
        v
  analytics.py scan ------------------> cached game analytics table
        |                                         |
        v                                         v
 Sport/date/quality controls -> game dropdown   load_game()
                                                  |
                                                  v
                                  trades_df + events + manifest + game_row
                                                  |
                             +--------------------+--------------------+
                             |                                         |
                             v                                         v
                   analyze_whales() -> whale_data            build_analysis_summary()
                             |                                         |
                             v                                         v
               whale_addresses + top_taker_whales         _build_analysis_card()
                             |
                             v
 load_or_compute_sensitivity() -> sensitivity rows
                             |
                             v
 build_charts(...) + sensitivity figures -> Figures
           _build_pregame_card() -> Card
             _build_whale_card() -> Card
```

## Key Design Decisions

- **Tip-off anchor:** First event's `time_actual` (median 24s into Q1) rather than `gamma_start_time` (scheduled, ~12 min early on median)
- **Tricode mapping:** Dynamic -- tracks which tricode increases away vs home score across events. No static lookup table needed.
- **Vertical lines:** Uses `add_shape` + `add_annotation` instead of `add_vline` (Plotly convenience method fails on datetime subplot axes)
- See `plans/NBA_Game_Visualizer_Plan.md` for full design rationale
