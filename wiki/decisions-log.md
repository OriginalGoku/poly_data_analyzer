# Decisions Log
<!-- Auto-maintained by /execute-plan and /retrospective. Do not edit manually. -->

## [retrospective: Price sensitivity plan completed with cached VWAP event analysis] 2026-04-11
**Salience:** MEDIUM
**Session:** post-execute-plan
**Modules:** settings.py, sensitivity.py, charts.py, pages/main_dashboard_page.py, tests/test_sensitivity.py
**Corrections:** none
**Reversals:** none
**Discoveries:** The sensitivity feature fit cleanly into the existing Dash/Plotly stack with no regressions. Per-event VWAP deltas, local disk caching under `cache/{date}/`, and the new timeline/surface views all validated against the full suite.
**Lesson:** For derived per-game analytics, keep the computation isolated in a dedicated module, cache the serialized result locally, and add the dashboard surfaces and tests in the same plan so the data path and presentation path stay aligned.

## [retrospective: Plotly add_vline fails on datetime subplot axes] 2026-04-09
**Salience:** HIGH
**Session:** freeform
**Modules:** charts.py
**Corrections:** none
**Reversals:** none
**Discoveries:** Plotly's `add_vline` with `annotation_text` silently fails or mispositions on subplots with datetime x-axes. Had to replace with explicit `add_shape` (vertical line) + `add_annotation` (label) calls to get correct placement.
**Lesson:** When drawing vertical reference lines on Plotly subplots with datetime axes, skip `add_vline`/`add_hline` convenience methods and use `add_shape` + `add_annotation` directly — the convenience wrappers have known issues with datetime positioning on multi-row subplot figures.

---

## [plan_file: Whale_Tracker_Plan.md] Executed 2026-04-10
**Mode:** sequential | **Result:** All 4 steps completed
**PRs:** N/A (sequential mode)
**Salience:** NONE
**Modules:** whales.py, charts.py, app.py, chart_settings.json, tests/test_whales.py
**Notable:** Execution matched plan.

---

## [plan_file: Buy Dips on Upper-Strong Favorit.md] Executed 2026-04-13
**Mode:** sequential | **Result:** All 8 steps completed
**PRs:** N/A (local commits only)
**Salience:** NONE
**Modules:** backtest_config.py, backtest_universe.py, dip_entry_detection.py, backtest_settlement.py, backtest_pnl.py, backtest_baselines.py, backtest_single_game.py, backtest_runner.py, backtest_export.py, backtest_cli.py, tests/test_backtest_*.py
**Notable:** Execution matched plan.

---

## [plan_file: NBA_Game_Visualizer_Plan.md] Executed 2026-04-09
**Mode:** sequential (3 waves) | **Result:** All 3 steps completed
**PRs:** N/A (sequential)
**Notable:** Plotly `add_vline` with `annotation_text` crashes on datetime subplot axes — switched to `add_shape` + `add_annotation`. Otherwise execution matched plan.

---

## [plan_file: Backtest_Correctness_Fixes_Plan.md] Executed 2026-04-14
**Mode:** sequential | **Result:** All 6 steps completed
**PRs:** N/A (committed directly to main)
**Salience:** HIGH
**Modules:** backtest/dip_entry_detection.py, backtest/backtest_pnl.py, backtest/backtest_config.py, backtest/backtest_runner.py, backtest/backtest_baselines.py, backtest/backtest_single_game.py, tests/test_backtest_*.py
**Notable:** Plan lacked `Depends on:` metadata so execution ran strictly sequentially rather than in parallel waves. Pre-existing `test_backtest_cli.py` had an import error (`backtest.backtest_cli` not found) because `backtest_cli.py` lives in the project root, not inside the `backtest/` package — pre-existing failure, not introduced. Step 6 caught that the `test_run_backtest_grid_multiple_configs` mock was missing the `gross_pnl_cents` field required by the new aggregation formula.
**Corrections:** none
**Reversals:** none
**Discoveries:** Mock objects in existing tests did not include all fields that new aggregation logic depends on — `gross_pnl_cents` was added to the formula in Step 5 but the Step 6 test-update pass was required to patch the mock, creating an implicit cross-step dependency the plan didn't model.
**Lesson:** When a plan step modifies an aggregation formula that consumes per-trade result objects, audit every existing mock/fixture for that object type before writing new tests — missing fields in mocks will fail silently at the mock level and loudly only at assertion time.

---
