# CLAUDE.md

## Commands

```bash
pip install -r requirements.txt   # install dependencies
python app.py                     # run Dash app on localhost:8050
```

## Structure

### Dashboard & Analytics
- `app.py` -- Dash app entry point (layout + callbacks + whale card builder)
- `analytics.py` -- Cached game-level checkpoint analytics, sport-specific quantile bands, and per-game regime summaries. Exposes `stream_game_analytics(...)` yielding `(base_record, get_game)` so per-game callers (e.g. NBA tipoff) read each `trades.json.gz` exactly once. Base-records frame persists cross-restart at `cache/_base_records/<settings_hash>.pkl` + `.manifest.json` (per-game `input_fingerprint`). `get_analytics_view` cache key no longer depends on `start_date`/`end_date`; the date filter is applied between sport filter and quantile_source so window-local bands are preserved. Base records project `pre_game_notional_usdc` and `trade_count` from `manifest.volume_stats`; `get_analytics_view(..., min_pregame_notional=X)` applies a post-cache hard gate against `pre_game_notional_usdc`.
- `charts.py` -- Plotly figure builders (pregame 3-row figure; in-game 4-row figure with whale markers and aggressor cumulative flow; sensitivity, discrepancy, regime transition, and dip recovery charts)
- `discrepancy.py` -- Cached market-score discrepancy intervals plus forward-return metrics
- `regime_transitions.py` -- Cached favorite-side band transition detection for the single-game dashboard
- `dip_recovery.py` -- Cached absolute dip interval detection and recovery summaries
- `sensitivity.py` -- Per-event scoring sensitivity computation and cache loader
- `loaders.py` -- Data loading and parsing. `load_game` delegates to `build_loaded_game(data_dir, date, manifest, trades_data, outlier_settings)` so streaming callers can hand in already-decompressed trades data without a second disk read.
- `nba_tipoff_cache.py` -- Persistent per-game disk cache for tipoff detail rows. Path: `cache/<date>/<match_id>_nba_tipoff.json`. Payload guarded by `schema_version` + `settings_hash` (over `pregame_min_cum_vol`, `vol_spike_std`, `vol_spike_lookback`, `post_game_buffer_min`, open-favorite team/price) + `input_fingerprint` (mtime+size of trades/manifest/events). Supports lazy `game_provider` so cache hits skip game I/O entirely.
- `whales.py` -- Whale wallet identification, classification, filtering, and maker/taker trade-size stats
- `band_drop_recovery.py` -- Per-band drop-recovery aggregator. Joins engine sweep output to base-records frame, computes recovery rate + Wilson 95% CI + median TTR + median further drawdown by `(band, drop_pct)`. Sibling to `dip_recovery.py`; no shared cache files.
- `pages/nba_band_drop_recovery_page.py` -- Band × drop-pct recovery grid (route `/nba-band-drop-recovery`). Page owns engine invocation against `band_drop_recovery_sweep` scenario; filters mirror tipoff page.

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
- `backtest/registry.py` -- three component registries (`UNIVERSE_FILTERS`, `TRIGGERS`, `EXITS`) plus parallel `*_SCHEMAS` dicts that expose each component's `PARAM_SCHEMA` for the builder UI
- `backtest/scenarios.py` -- scenario JSON loader with sweep expansion (parameter grids fan out into multiple scenarios)
- `backtest/scenarios/*.json` -- scenario definitions (e.g., `dip_buy_favorite.json`, `favorite_drop_50pct_60min_tp_sl.json`, `favorite_drop_50pct_unbounded_tp_sl.json`, `band_drop_recovery_sweep.json`)
- `backtest/filters/` -- universe filters (`upper_strong.py`, `first_k_above.py`)
- `backtest/triggers/` -- entry triggers (`dip_below_anchor.py`, `pct_drop_window.py`)
- `backtest/exits/` -- exits (`settlement.py`, `reversion_to_open.py`, `reversion_to_partial.py`, `fixed_profit.py`, `tp_sl.py`)
- `backtest/position_manager.py` -- `PositionManager`; supports `sequential` and `scale_in` lock modes
- `backtest/engine.py` -- registry-dispatched per-game loop; force-closes open positions at `game_end`
- `backtest/runner.py` -- orchestrates scenarios over a date range; produces per-position DataFrame plus aggregation DataFrame
- Side-aware: `scenario.side_target = "favorite" | "underdog"`
- New CLI flags: `--scenario`, `--scenarios-glob`, `--start-date`, `--end-date`, `--data-dir`, `--output`
- UI pages: `pages/scenario_builder_page.py` (`/scenario-builder`), `pages/scenario_runner_page.py` (`/scenario-runner`), `pages/scenario_results_page.py` (`/scenario-results`)
- Each filter/trigger/exit module declares a `PARAM_SCHEMA = [...]` constant (typed: `int|float|bool|enum|int_pair|nullable_int`, with optional `sweepable: True`); subpackage `__init__.py` registers it alongside the callable. Builder UI renders inputs from these schemas — no UI-side duplication.

### Configuration
- `chart_settings.json` -- Configurable thresholds (volume spikes, whale detection, whale marker minimum size, sensitivity windows/bins)

### Data & Docs
- `cache/` -- Local computed artifacts: per-game sensitivity, discrepancy, regime transition, dip recovery, and NBA tipoff detail JSON caches (`cache/<date>/<match_id>_<kind>.json`), plus the cross-restart base-records frame at `cache/_base_records/<settings_hash>.pkl` with a `.manifest.json` sidecar.
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
- `pregame_min_cum_vol` is dual-purpose: (a) cumulative trade `size` threshold for the meaningful-open anchor (share-count units in `_filter_by_min_cum_vol`); (b) USDC-notional hard gate (`min_pregame_notional`) against `manifest.volume_stats.pre_game_notional_usdc` in the main-dashboard game-picker. Same knob, different comparators — keep that in mind when tuning.
- `data_warning_min_pregame_vol` (default $20,000) is the soft threshold for the red "Likely truncated trade data" badge atop the game-card. Trade-count secondary signal: hardcoded `< 50` in `_build_data_warning_badge`.
- Per-game on-disk cache convention: `cache/<date>/<match_id>_<kind>.json` with payload `{schema_version, settings_hash, input_fingerprint?, row|rows}`. Used by `sensitivity`, `dip_recovery`, `regime_transitions`, `discrepancy`, and `nba_tipoff_cache`. Only `nba_tipoff_cache` includes `input_fingerprint` (raw-data mtime+size) because the tipoff page is the user-visible perf cache; the others rely on the implicit "raw data immutable once collected" contract.
- Bulk per-game pipelines (NBA tipoff) should consume `analytics.stream_game_analytics(...)` to read each `trades.json.gz` once; pair with a lazy `game_provider` callback so disk-cache hits avoid the load entirely. RAM stays at one game at a time.
- `_build_nba_analysis_dataset` emits stdout phase timers (`[nba_tipoff] base_records=… elapsed=…s`, `detail_loop`, `post_process`) visible in the Dash terminal; preserve them when refactoring.
