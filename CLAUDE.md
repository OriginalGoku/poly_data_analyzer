# CLAUDE.md

## Commands

```bash
pip install -r requirements.txt   # install dependencies
python app.py                     # run Dash app on localhost:8050
```

## Structure

### Dashboard & Analytics
- `app.py` -- Dash app entry point (layout + callbacks + whale card builder)
- `analytics.py` -- Cached game-level checkpoint analytics, sport-specific quantile bands, and per-game regime summaries. Exposes `stream_game_analytics(...)` yielding `(base_record, get_game)` so per-game callers (e.g. NBA tipoff) read each `trades.json.gz` exactly once. Base-records frame persists cross-restart at `cache/_base_records/<settings_hash>.pkl` + `.manifest.json` (per-game `input_fingerprint`). `get_analytics_view` cache key no longer depends on `start_date`/`end_date`; the date filter is applied between sport filter and quantile_source so window-local bands are preserved. Base records project `pre_game_notional_usdc` and `trade_count` from `manifest.volume_stats`, plus per-team in-game extremes (`away_in_game_min_price`, `away_in_game_max_price`, `home_in_game_min_price`, `home_in_game_max_price`) from the `ingame_extremes.py` sidecar; `BASE_RECORDS_CACHE_SCHEMA_VERSION = 2` (bumped from 1 when the extremes columns were added). `_load_base_records_cache` rejects pickles missing any extreme column to defend against future additive fields skipping a version bump. `get_analytics_view(..., min_pregame_notional=X)` applies a post-cache hard gate against `pre_game_notional_usdc`.
- `charts.py` -- Plotly figure builders (pregame 3-row figure; in-game 4-row figure with whale markers and aggressor cumulative flow; sensitivity, discrepancy, regime transition, and dip recovery charts)
- `discrepancy.py` -- Cached market-score discrepancy intervals plus forward-return metrics
- `regime_transitions.py` -- Cached favorite-side band transition detection for the single-game dashboard
- `dip_recovery.py` -- Cached absolute dip interval detection and recovery summaries
- `sensitivity.py` -- Per-event scoring sensitivity computation and cache loader
- `loaders.py` -- Data loading and parsing. `load_game` delegates to `build_loaded_game(data_dir, date, manifest, trades_data, outlier_settings)` so streaming callers can hand in already-decompressed trades data without a second disk read.
- `nba_analysis.py` -- NBA open-vs-tip-off analysis service + per-game detail metrics. `_compute_in_game_open_favorite_metrics` computes in-game min/max/MAE/MFE for **both** the open favorite and the tip-off favorite (parallel branches sharing `_in_game_excursion_metrics`); tip-off team/price are threaded from the base record (`analytics.py`), not from `compute_metrics`. `_compute_tipoff_entry_window_price` is the size-weighted avg favorite-side price of the last N pre-tip trades (`tipoff_favorite_avg_last_n_pretip_price`, `tipoff_entry_window_n_used`). `NBAOpenTipoffAnalysisService` exposes `build_band_outcome_distribution` (per-band×outcome min-price percentiles) and `build_band_stop_loss_ev_grid` (per-band EV-vs-stop grid with Wilson CIs + `is_argmax`; in-game min from a 5-min resample so EV is an upper bound).
- `analysis_nba_open_vs_tipoff.py` -- Export CLI. Emits `dataset.csv`, per-band summaries, plus `tipoff_band_min_price_distribution.csv`, `tipoff_band_stop_loss_ev.csv` (SL grid), `tipoff_band_take_profit_ev.csv` (TP-only grid, single-barrier), `tipoff_band_bracket_ev.csv` (TP×SL bracket, first-passage), and `tipoff_stop_loss_oos_validation.csv` (chronological 70/30 train/test overfit check). Appends matching argmax sections to `summary.md`. Baseline archival: `scripts/archive_baseline_pre_tipoff_stoploss.sh`.
- `nba_tipoff_bracket.py` -- Per-band TP×SL bracket EV grid via **full-resolution first-passage**: walks each game's favorite-side trade path once (`cummax`/`cummin` + vectorized `searchsorted`), resolving TP-before-SL ordering (ties→TP, like `backtest.exits.tp_sl`). Streams each game once via `stream_game_analytics` (one extra full trades read beyond the detail loop — the dominant cost of the analysis CLI). TP = limit sell (no slippage), SL = market order (slippage). Unlike the scalar SL/TP grids in `nba_analysis` (5-min resample, upper-bound EV), this uses the raw path so EV is realistic.
- `nba_tipoff_cache.py` -- Persistent per-game disk cache for tipoff detail rows. Path: `cache/<date>/<match_id>_nba_tipoff.json`. `NBA_TIPOFF_CACHE_SCHEMA_VERSION = 2` (bumped from 1 when tip-off-favorite in-game + entry-window columns were added). Payload guarded by `schema_version` + `settings_hash` (over `pregame_min_cum_vol`, `vol_spike_std`, `vol_spike_lookback`, `post_game_buffer_min`, `tipoff_entry_window_trades`, open-favorite team/price) + `input_fingerprint` (mtime+size of trades/manifest/events). Supports lazy `game_provider` so cache hits skip game I/O entirely.
- `whales.py` -- Whale wallet identification, classification, filtering, and maker/taker trade-size stats
- `ingame_extremes.py` -- Per-team in-game min/max price sidecar (settings-independent). Path `cache/<date>/<match_id>_ingame_extremes.json`. Payload `{schema_version, input_fingerprint, row}` with no `settings_hash` field; window resolves via score events → gamma_closed_time → gamma_start fallback. `load_or_compute_ingame_extremes` supports lazy `game_provider` so cache hits skip game I/O. Backfill: `scripts/backfill_ingame_extremes.py`.
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
- Per-game on-disk cache convention: `cache/<date>/<match_id>_<kind>.json` with payload `{schema_version, settings_hash?, input_fingerprint?, row|rows}`. Used by `sensitivity`, `dip_recovery`, `regime_transitions`, `discrepancy`, `nba_tipoff_cache`, and `ingame_extremes`. `nba_tipoff_cache` and `ingame_extremes` both carry `input_fingerprint` (raw-data mtime+size). `ingame_extremes` is the only sidecar that omits `settings_hash` — extremes are settings-independent and survive future settings-hash changes without recompute.
- `chart_settings.json` key `max_favorite_price_threshold` (default 0.97) is the default value for the main-dashboard "Max anchor-side price" filter. Combined with the Bucket Anchor dropdown, it lets the picker drop games whose anchor-side favorite ever reached the threshold price in-game.
- `chart_settings.json` keys for tip-off stop-loss EV: `tipoff_entry_window_trades` (default 30; N pre-tip favorite-side trades size-weighted into the entry price — also part of `nba_tipoff_cache` settings hash), `stop_loss_fee_bps` and `stop_loss_slippage_bps` (default 0.0; frictionless EV baseline — tune before claiming positive EV).
- Bulk per-game pipelines (NBA tipoff) should consume `analytics.stream_game_analytics(...)` to read each `trades.json.gz` once; pair with a lazy `game_provider` callback so disk-cache hits avoid the load entirely. RAM stays at one game at a time.
- `_build_nba_analysis_dataset` emits stdout phase timers (`[nba_tipoff] base_records=… elapsed=…s`, `detail_loop`, `post_process`) visible in the Dash terminal; preserve them when refactoring.
