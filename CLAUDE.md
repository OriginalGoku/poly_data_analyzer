# CLAUDE.md

## Commands

```bash
pip install -r requirements.txt   # install dependencies
python app.py                     # run Dash app on localhost:8050
```

## Structure

### Dashboard & Analytics
- `app.py` -- Dash app entry point (layout + callbacks + whale card builder)
- `analytics.py` -- Cached game-level checkpoint analytics, sport-specific quantile bands, and per-game regime summaries
- `charts.py` -- Plotly figure builders (pregame 3-row figure; in-game 4-row figure with whale markers and aggressor cumulative flow; sensitivity, discrepancy, regime transition, and dip recovery charts)
- `discrepancy.py` -- Cached market-score discrepancy intervals plus forward-return metrics
- `regime_transitions.py` -- Cached favorite-side band transition detection for the single-game dashboard
- `dip_recovery.py` -- Cached absolute dip interval detection and recovery summaries
- `sensitivity.py` -- Per-event scoring sensitivity computation and cache loader
- `loaders.py` -- Data loading and parsing
- `whales.py` -- Whale wallet identification, classification, filtering, and maker/taker trade-size stats

### Backtest Framework (legacy; slated for removal in Step 19)
- `backtest/backtest_cli.py` -- legacy CLI; parses date range, dip thresholds, exit types, fee models, sport filters
- `backtest/backtest_config.py` -- `DipBuyBacktestConfig` frozen dataclass
- `backtest/backtest_runner.py` -- legacy grid orchestration
- `backtest/backtest_single_game.py` -- legacy single-game orchestration
- `backtest/backtest_baselines.py` -- baseline strategies (buy-at-open, buy-at-tipoff, buy-first-in-game)
- `backtest/backtest_universe.py` -- legacy universe filtering
- `backtest/dip_entry_detection.py` -- legacy dip touch detection
- `backtest/backtest_settlement.py` -- resolves settlement prices from events/trades
- `backtest/backtest_pnl.py` -- trade-level PnL with Polymarket fees
- `backtest/backtest_export.py` -- CSV/JSON export and heatmap visualizations
- UI pages: `pages/backtest_runner_page.py`, `pages/backtest_results_page.py`

### New Backtest Engine (parallel to legacy; scenario-driven)
Generic JSON-scenario-driven engine. Components are pluggable and decorator-registered; scenarios composed from filter/trigger/exit specs. Both engines are wired up; legacy will be deleted in Step 19 after the manual 2-week gate.
- `backtest/contracts.py` -- frozen dataclass contracts: `Context`, `Trigger`, `Exit`, `Position`, `Scenario`, `LockSpec`, `ComponentSpec`, `GameMeta`
- `backtest/registry.py` -- three component registries: `UNIVERSE_FILTERS`, `TRIGGERS`, `EXITS`
- `backtest/scenarios.py` -- scenario JSON loader with sweep expansion (parameter grids fan out into multiple scenarios)
- `backtest/scenarios/*.json` -- scenario definitions (e.g., `dip_buy_favorite.json`, `favorite_drop_50pct_60min_tp_sl.json`, `favorite_drop_50pct_unbounded_tp_sl.json`)
- `backtest/filters/` -- universe filters (`upper_strong.py`, `first_k_above.py`)
- `backtest/triggers/` -- entry triggers (`dip_below_anchor.py`, `pct_drop_window.py`)
- `backtest/exits/` -- exits (`settlement.py`, `reversion_to_open.py`, `reversion_to_partial.py`, `fixed_profit.py`, `tp_sl.py`)
- `backtest/position_manager.py` -- `PositionManager`; supports `sequential` and `scale_in` lock modes
- `backtest/engine.py` -- registry-dispatched per-game loop; force-closes open positions at `game_end`
- `backtest/runner.py` -- orchestrates scenarios over a date range; produces per-position DataFrame plus aggregation DataFrame
- Side-aware: `scenario.side_target = "favorite" | "underdog"`
- New CLI flags: `--scenario`, `--scenarios-glob`, `--start-date`, `--end-date`, `--data-dir`, `--output`
- UI pages: `pages/scenario_runner_page.py` (`/scenario-runner`), `pages/scenario_results_page.py` (`/scenario-results`)

### Configuration
- `chart_settings.json` -- Configurable thresholds (volume spikes, whale detection, whale marker minimum size, sensitivity windows/bins)

### Data & Docs
- `cache/` -- Local computed artifacts such as per-game sensitivity, discrepancy, regime transition, and dip recovery JSON caches
- `DATA_SPEC.md` -- Upstream data format reference (from poly-data-downloader)
- `data/` -- Trade data directories (YYYY-MM-DD format, not checked in)

## Key Patterns

- Data comes from `poly-data-downloader` -- see `DATA_SPEC.md` for schema
- `outcomes[0]` / `token_ids[0]` = away team, `[1]` = home team
- UI is multi-sport (`nba`, `nhl`, `mlb`), but event quality still varies by sport; missing events should degrade gracefully
- NBA events use `time_actual` (UTC wall-clock), directly comparable to trade timestamps
- Tricode-to-team mapping is built dynamically from score changes in events (no static lookup)
- `gamma_start_time` is scheduled start (can be ~12 min off); first event `time_actual` is actual tip-off
- Use `add_shape` + `add_annotation` for vertical lines on Plotly subplots (not `add_vline`)
- Whale classification: Market Maker (high maker %, 20+ trades), Directional (high taker %), Hybrid (mixed). Side attribution is taker-only; maker flow is passive.
- `Top Aggressors (Takers)` excludes wallets classified as `Market Maker` even if they have trivial taker flow.
- In-game price markers and the extra cumulative whale panel are driven by the ranked top-10 taker whales.
- `chart_settings.json` controls whale detection thresholds (`whale_min_volume_pct`, `whale_max_count`, `whale_maker_threshold_pct`) plus `whale_marker_min_trade_pct` for suppressing small plotted whale trades.
- Regime analytics should be built from favorite-side probabilities, not both token prices independently.
- Quantile bands are computed separately by sport and by active `price_quality` slice.
- The analytics `open` anchor is a "meaningful open": first pregame trade prices after cumulative pregame volume reaches `pregame_min_cum_vol`, not raw `selected_early_price`.
