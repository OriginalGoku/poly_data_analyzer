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
- analytics.py — game-record builder + get_analytics_view (sport/date/quality/min_pregame_notional filters + quantile bands)
- backtest_cli.py — scenario CLI argument parsing + selection
- charts.py — Plotly figure builders; pure helpers: _get_tipoff, _get_game_end, _collect_vmarkers, _filter_by_min_cum_vol, _nearest_price
- analysis_nba_open_vs_tipoff.py — CSV/summary export script (write_summary_file + main emit tip-off band distribution + stop-loss EV outputs)
- loaders.py — Data loading/parsing; pure helpers: _is_date_dir, _parse_iso, _build_tricode_map
- nba_analysis.py — NBAOpenTipoffAnalysisService (band outcome distribution + stop-loss EV grid) + pure helpers: _in_game_excursion_metrics, _compute_in_game_open_favorite_metrics, _resolve_score_tipoff_time, _compute_tipoff_entry_window_price, _compute_nba_detail_row_from_game
- nba_tipoff_cache.py — compute_settings_hash + load_or_compute_nba_tipoff_detail (schema/settings/fingerprint invalidation)
- pages/main_dashboard_page.py — pure helpers: _build_data_warning_badge, _normalize_date_range, _encode_game_value/_decode_game_value
- settings.py — ChartSettings defaults + to_dict roundtrip
- whales.py — Whale wallet analysis: analyze_whales (classification, thresholds, summary), get_whale_trades (filtering)
