# Testable Modules
<!-- Auto-maintained by /test-epilogue — do not edit manually -->

- backtest/backtest_export.py — per-position CSV/JSON export + heatmap
- backtest/contracts.py — frozen dataclasses + Context.slice_after cursor helper
- backtest/engine.py — fee_pct_for resolver + run_scenario_on_game per-game loop
- backtest/exits/{settlement,reversion_to_open,reversion_to_partial,fixed_profit,tp_sl}.py — exit scanner factories
- backtest/filters/{upper_strong,first_k_above}.py — universe filters
- backtest/position_manager.py — PositionManager (sequential/scale_in lock modes, cooldowns, stop-loss arming)
- backtest/runner.py — grid runner, universe caching, per-position row build, aggregation
- backtest/scenarios.py — JSON loader with sweep expansion
- backtest/triggers/{dip_below_anchor,pct_drop_window}.py — trigger scanners
- backtest_cli.py — scenario CLI argument parsing + selection
- charts.py — Plotly figure builders; pure helpers: _get_tipoff, _get_game_end, _collect_vmarkers, _filter_by_min_cum_vol, _nearest_price
- loaders.py — Data loading/parsing; pure helpers: _is_date_dir, _parse_iso, _build_tricode_map
- whales.py — Whale wallet analysis: analyze_whales (classification, thresholds, summary), get_whale_trades (filtering)
