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

## [plan_file: Backtest_Engine_Redesign_Technical_Plan.md] Executed 2026-04-25
**Mode:** parallel (6 waves) | **Result:** 18 of 19 steps completed (Step 19 is a manual-gated 2-week sunset, intentionally deferred)
**PRs:** #1–#18 (all squash-merged to main)
**Salience:** HIGH
**Modules:** backtest/, backtest/exits/, backtest/filters/, backtest/triggers/, backtest/scenarios.py, backtest_cli.py, backtest_export.py, tests/
**Notable:** Test count grew 205 -> 324 with no new regressions (the 13 remaining failures match the pre-existing baseline set; Step 18 incidentally fixed the prior `test_backtest_cli.py` collection error). Four notable execution surprises: (1) GitHub squash-merges diverged local/origin when the plan-commit was unpushed but PRs branched from it — required `git pull --rebase` to reconcile on first wave. (2) Step 4 making team/token_id/side required transiently broke 11 old-engine tests; Step 6 fixed 7 baseline ones; the 4 single_game ones stay broken until the deferred Step 19 sunset. (3) Wave 4 ran the export rewrite (Step 16) and CLI rewrite (Step 18) in parallel from the same base; CLI was written against the pre-#16 export signature and produced a runtime TypeError that the orchestrator caught in post-merge tests and patched. (4) Filters/triggers package init files didn't auto-register because top-level `backtest/__init__.py` wasn't importing the new sub-packages — orchestrator patched after Wave 2 by adding explicit `import backtest.exits` / `import backtest.filters` lines.
**Corrections:** Orchestrator patched two coordination bugs after merges (CLI<->export signature mismatch; package registry not populating on `import backtest`). Bash HEREDOC quoting bug corrupted Wave 2 prompts via unquoted backticks expanding as command substitution; resolved by switching to single-quoted HEREDOCs.
**Reversals:** none
**Discoveries:** Two parallel agents (Step 8, Step 10) silently expanded scope beyond their declared `Files:` lists — Step 8 modified `backtest/__init__.py`, Step 10 added a ValueError to `backtest/scenarios.py` for empty sweep. Both were benign improvements but indicate parallel agents will quietly fix adjacent issues without flagging.
**Lesson:** When orchestrating parallel waves where steps share a downstream consumer (e.g. export <-> CLI), force the consumer's wave to start strictly after the producer's signature lands — a same-base parallel split between a function rewrite and its caller is a guaranteed runtime break. Also: any plan that introduces a new sub-package with auto-registration via `__init__.py` must include an explicit step to wire the parent package's `__init__.py` to import it, or registries will silently stay empty under partial imports.

---

## [plan_file: NBA_Tipoff_Page_Performance_Plan/technical-plan.md] Executed 2026-05-16
**Mode:** sequential | **Result:** All 7 steps completed
**PRs:** N/A (sequential mode, direct edits to main, uncommitted)
**Salience:** HIGH
**Modules:** analytics.py, pages/nba_tipoff_page.py, tests/test_analytics.py, tests/test_nba_tipoff_cache.py
**Notable:** User chose sequential over plan's parallel-worktree mode for simplicity. Parquet dep absent (no pyarrow/fastparquet), so base-records cache uses pickle instead — works fine for this artifact. Test count 244 -> 252 (+1 quantile-band regression guard, +7 new cache tests).
**Corrections:** none
**Reversals:** none
**Discoveries:** Plan's base-records cache only avoids one of two file reads on cross-cache warm path. To make warm path truly zero-IO, refactored `stream_game_analytics` to yield `(base_record, get_game)` with a memoized `get_game` callable, and threaded a `game_provider` parameter through `load_or_compute_nba_tipoff_detail`. This lazy-loader shape was not in the plan but is required for the caches to compose.
**Lesson:** When stacking two caches over a shared upstream read, design the producer to yield a lazy accessor for the expensive payload — otherwise the second cache's hit path still pays the upstream IO cost. Pair semantic-preservation requirements (e.g., filter ordering for quantile bands) with a regression test in the same plan step so the invariant is enforced, not just documented.

---

## [plan_file: technical-plan.md] Executed 2026-05-16
**Mode:** parallel (5 waves nominal; ran inline) | **Result:** All 7 steps completed
**PRs:** N/A (committed directly to main)
**Salience:** HIGH
**Modules:** features/statistical-odd-analyzer, backtest/exits, backtest/engine, tests/
**Notable:** Wiring band-drop-recovery exposed two latent backtest-engine bugs the plan assumed away. Test count 265 -> 288 (+23, 0 regressions).
**Corrections:** none
**Reversals:** none
**Discoveries:** (1) `ExitScanner` dataclass instances were not callable, but `PositionManager` invoked them as callables — broken since introduction, masked because existing engine tests used plain closures. Fixed in `backtest/exits/__init__.py`. (2) `engine.run_game` never ticked `PositionManager` at `game_end` before `force_close`, so scanner-driven exits (e.g. `reversion_to_open`) never observed the full tape under `sequential` lock mode. Fixed in `backtest/engine.py`.
**Lesson:** When a plan declares existing primitives "reusable as-is," add at least one integration test that exercises the full call path (PM.tick + dataclass-style exit + lock mode) before trusting the assumption — pure-unit tests of each layer in isolation will miss cross-component contract drift. Reach for the smallest end-to-end fixture, not more unit coverage.
**Architecture gate output:**
```text
sentrux gate — structural regression check

Quality:      6369 -> 6364
Coupling:     0.02 → 0.02
Cycles:       0 → 0
God files:    0 → 0

Distance from Main Sequence: 0.35

✗ DEGRADED
  ✗ Complex functions increased: 12 → 13
```
**Regressions introduced:** complex functions 12 -> 13 (advisory)
**Regressions fixed:** none
**Intentional tradeoffs:** Accepted one additional complex function for the band-drop-recovery wiring; quality score net-improved (6369 -> 6364, lower is better).

---
