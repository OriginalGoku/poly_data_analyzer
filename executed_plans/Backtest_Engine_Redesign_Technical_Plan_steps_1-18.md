# Backtest Engine Redesign — Technical Plan

> Rip-and-replace the dip-buy backtester with a generic, JSON-scenario-driven engine where universe filters, triggers, and exits are independently registered components and scale-in (multi-position) per game is first-class.

---

## Problem Statement

Current backtester (`backtest/backtest_single_game.py`, `backtest_runner.py`, `dip_entry_detection.py`) is hard-coded to one strategy: dip-buy on the open favorite, single entry per game, settlement-or-reversion exit. To experiment with new triggers (e.g. `pct_drop_window`), new exits (`tp_sl`), the underdog side, scale-in entries, and scenario sweeps, the engine needs to be decomposed into a registry-driven component system with declarative JSON scenarios, a per-game `PositionManager`, and per-position output rows. Old single-entry semantics are dropped — every strategy is treated as scale-in-capable.

## Codebase Context

Verified state of files the plan touches:

- `backtest/backtest_pnl.py` — `compute_trade_pnl(entry, exit_, settlement, fee_model, fee_pct, settings)`. Entry dict currently carries only `entry_price`, `entry_time`. Needs `team`, `token_id`, `side`.
- `backtest/backtest_settlement.py` — `resolve_settlement(..., open_favorite_team=None)`. Logic is favorite-only (`payout = 1.0 if winner_team == open_favorite_team`). Needs `entry_team` rename and a flag for which side wins.
- `backtest/backtest_baselines.py` — three `baseline_*` fns each take `open_favorite_team`. Need to accept `entry_team` and short-circuit to NaN when called for non-favorite side.
- `backtest/dip_entry_detection.py` — has `find_dip_entry` (port to `dip_below_anchor` trigger) and `find_exit` with four `exit_type` branches (port to four exit modules). Currently re-filters trades by `trades_df["datetime"] > t` per call — the new contract pre-builds `trades_time_array` and uses `np.searchsorted`.
- `backtest/backtest_universe.py` — `filter_upper_strong_universe` returns a list of tuples. Port to `filters/upper_strong.py` with a registry-friendly signature.
- `backtest/backtest_runner.py` and `backtest/backtest_single_game.py` — the orchestration to be replaced wholesale.
- `loaders.py:load_game` returns `trades_df` already keyed by `team` (line 142 in old single_game confirms `trades_df[trades_df["team"] == open_favorite_team]` works), so per-team slicing is native — no `1 − price` reconstruction required.
- `pages/backtest_runner_page.py`, `pages/backtest_results_page.py` — old UI pages, kept alive via the not-yet-deleted old runner until the 2-week sunset window in Step 19.
- `tests/` — has `test_backtest_pnl.py`, `test_backtest_settlement.py`, `test_backtest_baselines.py`, `test_backtest_universe.py`, `test_dip_entry_detection.py`, `test_backtest_runner.py`, `test_backtest_single_game.py`, `test_backtest_cli.py`, `test_backtest_export.py`. First three keep passing through migration; bottom four are deleted in Step 19.
- `app.py` registers pages — must be updated when new UI pages land.

Prior decision-log notes (HIGH salience, overlapping modules):
- `Backtest_Correctness_Fixes_Plan.md` retrospective: mocks may miss new aggregation fields. **Apply: when changing the per-position result schema in Step 15/16, audit every existing mock/fixture in `tests/test_backtest_*.py` for missing fields before writing assertions.**

No `DESIGN.md`, no `AUDIT_REPORT.md`, no `.repo-index/`.

## Implementation Steps

### Step 1: Core contracts, registry, scenario loader (skeleton)
Files: backtest/contracts.py, backtest/registry.py, backtest/scenarios.py, backtest/__init__.py
Depends on: none

**What changes:**
- `backtest/contracts.py` — new. Frozen dataclasses: `Context`, `Trigger`, `Exit`, `Position`, `Scenario`, `LockSpec`, `ComponentSpec`, `GameMeta`. Field set per plan §"Core Data Contracts". `Context` exposes `slice_after(after_time, team=None) -> pd.DataFrame` using `np.searchsorted` over `trades_time_array`.
- `backtest/registry.py` — new. Three module-level dicts: `UNIVERSE_FILTERS`, `TRIGGERS`, `EXITS`. No decorators; explicit registration via subpackage `__init__.py` files.
- `backtest/scenarios.py` — new. `load_scenarios(scenarios_dir="backtest/scenarios") -> dict[str, Scenario]`. Glob `*.json`, parse, expand `{"sweep": [...]}` leaves into Cartesian product of concrete scenarios with names `<base>__<dot.path>=<value>`. Validate scenario-name uniqueness, schema (required keys: `name`, `universe_filter`, `side_target`, `trigger`, `exit`, `lock`, `fee_model`).
- `backtest/__init__.py` — re-export public types and registries.

**Key details:**
- `Context.trades_time_array` is `np.ndarray` of datetime64 values, sorted, built once at Context construction.
- `slice_after` returns a view (no copy); read-only inside scanners.
- Sweep marker is exactly `{"sweep": [...]}` — bare lists are literal params. Loader rejects ambiguous shapes.

**Test strategy:**
- Defer dedicated tests to Step 2/Step 10. Smoke: `from backtest import Context, Trigger, Exit, Scenario` succeeds.

---

### Step 2: PositionManager + invariant tests
Files: backtest/position_manager.py, tests/test_position_manager.py, tests/test_forced_close_invariant.py
Depends on: Step 1

**What changes:**
- `backtest/position_manager.py` — new. `PositionManager(lock: LockSpec)`. API: `can_open(now)`, `register_position(pos, exit_scanner)`, `tick(ctx, now)`, `next_eligible_time(now, game_end)`, `force_close_all(at)`, `exhausted()`.
  - `sequential` mode: at most one open. `can_open` requires `now >= last_exit_time + cool_down_seconds`; if `allow_re_arm_after_stop_loss=False` and last `exit_kind=="stop_loss"`, block re-entry permanently for the game.
  - `scale_in` mode: up to `max_entries` concurrent. `can_open` gated by `now >= last_entry_time + cool_down_seconds` AND `total_entries < max_entries`. `allow_re_arm_after_stop_loss` ignored (warn at construction if set).
  - `force_close_all(at)` synthesizes `Exit(exit_time=at, exit_price=<last in-game price for that team>, exit_kind="forced_close", status="forced_close")` for every still-open position.

**Key details:**
- All `Exit` objects must have a non-None `exit_time` — no exception paths.
- `next_eligible_time` returns earliest of: cooldown end, next open-eligible timestamp, or `game_end`. Lets engine advance cursor instead of busy-looping.

**Test strategy:**
- `tests/test_position_manager.py`: sequential single-entry; cool-down gating; `allow_re_arm_after_stop_loss=False` blocks; scale_in concurrent up to `max_entries`; min-spacing; `force_close_all`; `exhausted()`.
- `tests/test_forced_close_invariant.py`: every emitted `Exit` has non-None `exit_time`.

---

### Step 3: Engine loop + scanner cursor tests
Files: backtest/engine.py, tests/test_engine.py, tests/test_scanner_cursor.py
Depends on: Step 2

**What changes:**
- `backtest/engine.py` — new. `run_scenario_on_game(scenario, ctx) -> list[Position]` per plan §"Engine Loop". Uses `TRIGGERS`/`EXITS` registries. After main loop, calls `pm.force_close_all(ctx.game_end)`, then loops positions to call `resolve_settlement(..., entry_team=pos.trigger.team)` and `compute_trade_pnl(...)`.
- Helper `fee_pct_for(fee_model)` reads from `chart_settings.json` via `settings`.

**Key details:**
- Cursor advances by `trigger.trigger_time + 1µs` after each fire; if trigger returns None the loop breaks.
- If `pm.can_open` is False, cursor jumps to `pm.next_eligible_time(...)`.
- Engine never re-filters `trades_df` directly — every read goes through `ctx.slice_after`.

**Test strategy:**
- `tests/test_engine.py`: sequential blocks until exit fires; scale_in produces N concurrent positions; forced_close at game_end populates remaining positions; `position_index_in_game` increments 0,1,2…
- `tests/test_scanner_cursor.py`: edge timestamps for `slice_after`; perf-shape assertion that 1000 sequential calls on 100k-trade df complete in < N ms.

---

### Step 4: Side-aware compute_trade_pnl
Files: backtest/backtest_pnl.py, tests/test_backtest_pnl.py
Depends on: none

**What changes:**
- `compute_trade_pnl` — entry dict now requires `team`, `token_id`, `side` plus existing keys. Returned dict propagates them. No PnL math change.
- `tests/test_backtest_pnl.py` — fixtures gain three new keys; new test asserts round-trip.

**Key details:**
- `side` is `Literal["favorite", "underdog"]`. PnL math symmetric (price = implied prob of entry token winning).

---

### Step 5: Side-aware resolve_settlement
Files: backtest/backtest_settlement.py, tests/test_backtest_settlement.py
Depends on: none

**What changes:**
- Rename param `open_favorite_team` → `entry_team`. Logic: `payout = 1.0 if winner_team == entry_team else 0.0`.
- Add temporary kw alias `open_favorite_team` forwarding to `entry_team` so old `backtest_single_game.py` keeps working until Step 19.
- `tests/test_backtest_settlement.py` — duplicate one test using `entry_team`; keep one with alias for backward compat.

**Test strategy:**
- New tests: underdog `entry_team` wins → payout=1.0; underdog loses → payout=0.0.

---

### Step 6: Side-aware baselines
Files: backtest/backtest_baselines.py, tests/test_backtest_baselines.py
Depends on: Step 5

**What changes:**
- Three `baseline_*` fns accept `entry_team` (alias `open_favorite_team` retained until Step 19) and `side: str = "favorite"`. When `side != "favorite"`, return NaN-shaped result (`roi_pct=NaN`, all numerics NaN, `status="skipped_non_favorite"`).
- Forward `entry_team` into `resolve_settlement(entry_team=...)`.

**Test strategy:**
- New: `side="underdog"` short-circuits to NaN dict; `side="favorite"` matches existing behavior.

---

### Step 7: Port universe filter — upper_strong
Files: backtest/filters/__init__.py, backtest/filters/upper_strong.py, tests/test_filters_upper_strong.py
Depends on: Step 1

**What changes:**
- `backtest/filters/upper_strong.py` — `def upper_strong(start_date, end_date, params: dict) -> list[GameMeta]`. Ports `filter_upper_strong_universe`. `params`: `min_open_favorite_price` (default 0.85), `exclude_inferred_price_quality`, `pregame_min_cum_vol`, `open_anchor_stat`, `open_anchor_window_min`. Returns `GameMeta` (frozen dataclass in `contracts.py`: `date, match_id, sport, open_fav_price, tipoff_fav_price, open_fav_token_id, can_settle, price_quality, open_favorite_team`).
- `backtest/filters/__init__.py` — registers `upper_strong`.

**Test strategy:**
- Port the cases from `test_backtest_universe.py`: open price threshold, tie exclusion, zero in-game volume exclusion, inferred quality exclusion, date range bounds, settlement-derivability flag, missing analytics rows.

---

### Step 8: Port dip_below_anchor trigger + component parity test
Files: backtest/triggers/__init__.py, backtest/triggers/dip_below_anchor.py, tests/test_triggers_dip_below_anchor.py, tests/test_dip_buy_component_parity.py
Depends on: Step 1

**What changes:**
- `backtest/triggers/dip_below_anchor.py` — `def dip_below_anchor(ctx, after_time, params) -> Trigger | None`. `params`: `anchor` ("open"|"tipoff"), `threshold_cents` (int). Resolves anchor from `ctx.open_prices[ctx.favorite_team]` or tipoff dict. Slices via `ctx.slice_after(after_time, team=ctx.favorite_team)`. First trade where `price <= anchor_price - threshold_cents/100`.
- `backtest/triggers/__init__.py` — registers `dip_below_anchor`.

**Test strategy:**
- Port cases from `test_dip_entry_detection.py::TestFindDipEntry`.
- `tests/test_dip_buy_component_parity.py` — fixture of 5 saved game JSONs. Assert new trigger returns same `(timestamp, price)` as `find_dip_entry`. Lock-policy-independent.

---

### Step 9: Port four exit components
Files: backtest/exits/__init__.py, backtest/exits/settlement.py, backtest/exits/reversion_to_open.py, backtest/exits/reversion_to_partial.py, backtest/exits/fixed_profit.py, tests/test_exits_settlement.py, tests/test_exits_reversion_to_open.py, tests/test_exits_reversion_to_partial.py, tests/test_exits_fixed_profit.py
Depends on: Step 1, Step 5

**What changes:**
- Each exit module exports `def <name>(ctx, trigger, params) -> ExitScanner`. `ExitScanner.scan(ctx, now) -> Exit | None`.
  - `settlement.py` — scanner is no-op; engine force-closes at `game_end`. After force-close, engine populates settlement payout via `resolve_settlement`.
  - `reversion_to_open.py` — first trade `>= trigger.anchor_price`. `exit_kind="reversion"`.
  - `reversion_to_partial.py` — params `partial_cents`. Target `= anchor - partial_cents/100`. `exit_kind="reversion"`.
  - `fixed_profit.py` — params `profit_cents`. Target `= entry_price + profit_cents/100`. `exit_kind="take_profit"`.
- `backtest/exits/__init__.py` — registers all four.

**Test strategy:**
- One test file per exit; port the corresponding branch from `test_dip_entry_detection.py::TestFindExit`.

---

### Step 10: dip_buy scenario JSON + scenarios loader test
Files: backtest/scenarios/dip_buy_favorite.json, tests/test_scenarios_loader.py
Depends on: Step 1

**What changes:**
- `backtest/scenarios/dip_buy_favorite.json` — exactly per plan example: `threshold_cents: {"sweep": [10, 15, 20]}`, `lock.mode="scale_in"`, `max_entries=5`, `cool_down_seconds=0`.
- `tests/test_scenarios_loader.py`: parse → 3 concrete scenarios named `dip_buy_favorite__trigger.threshold_cents=10|15|20`; empty sweep → ValueError; single-value sweep → 1 scenario; multi-axis cartesian; duplicate name across files → error; bare list (`window_seconds_after_tipoff: [0, 3600]`) treated as literal; missing required key → schema error.

---

### Step 11: pct_drop_window trigger
Files: backtest/triggers/pct_drop_window.py, backtest/triggers/__init__.py, tests/test_triggers_pct_drop_window.py
Depends on: Step 8

**What changes:**
- `pct_drop_window.py` — params: `anchor`, `drop_pct` (e.g. 50.0), `window_seconds_after_tipoff` (`[lo, hi]` or `null`). Computes `target = anchor_price * (1 - drop_pct/100)`. If window non-null, restricts to `tipoff_time + lo <= t < tipoff_time + hi`; if `null`, scans entire post-tipoff stream. Reads side from `ctx.scenario.side_target`.
- Register in `triggers/__init__.py` (file shared with Step 8 → sequential dep).

**Test strategy:**
- Bounded window — fires only inside; outside-window touches ignored. Unbounded equivalent. Anchor switch. Never-fires path. Edge: trade at exact lower bound included, upper bound excluded.

---

### Step 12: first_k_above universe filter
Files: backtest/filters/first_k_above.py, backtest/filters/__init__.py, tests/test_filters_first_k_above.py
Depends on: Step 7

**What changes:**
- `first_k_above.py` — `def first_k_above(start_date, end_date, params) -> list[GameMeta]`. `params`: `k`, `min_price`. Per candidate game: load first K post-tipoff favorite-side trades; include iff all K prices `>= min_price`.
- Register in `filters/__init__.py` (shared with Step 7).

**Test strategy:**
- Synthetic games — fewer than K (excluded), exactly K all above (included), K with one below (excluded), K with Kth at exactly `min_price` (included, ≥).

---

### Step 13: tp_sl exit
Files: backtest/exits/tp_sl.py, backtest/exits/__init__.py, tests/test_exits_tp_sl.py
Depends on: Step 9

**What changes:**
- `tp_sl.py` — params: `take_profit_cents` (int|null), `stop_loss_cents` (int|null), `max_hold_seconds` (int|null). Computes TP/SL targets and `deadline`. Scanner advances via `ctx.slice_after(now, team=trigger.team)`. TP if `price >= tp` → `take_profit`; SL if `price <= sl` → `stop_loss`; if `now >= deadline` → `max_hold`. First condition wins. If single trade satisfies both TP and SL (misconfig) → TP wins, warn.
- Register in `exits/__init__.py` (shared with Step 9).

**Test strategy:**
- TP-first; SL-first; max_hold-first; none-fire (engine force-closes); simultaneous TP/SL on same trade → TP; null `max_hold_seconds` → no deadline; null `take_profit_cents` → SL-only.

---

### Step 14: Two more scenario JSONs
Files: backtest/scenarios/favorite_drop_50pct_60min_tp_sl.json, backtest/scenarios/favorite_drop_50pct_unbounded_tp_sl.json
Depends on: Step 10, Step 11, Step 12, Step 13

**What changes:**
- Both files exactly per plan examples. Unbounded variant uses `"window_seconds_after_tipoff": null` and `"max_hold_seconds": null`.

**Test strategy:**
- Extend `tests/test_scenarios_loader.py` to assert both files parse and reference live components in `UNIVERSE_FILTERS`/`TRIGGERS`/`EXITS`.

---

### Step 15: Runner — grid orchestration + per-position output + underdog test
Files: backtest/runner.py, tests/test_runner.py, tests/test_underdog_path.py
Depends on: Step 3, Step 6, Step 7, Step 8, Step 9, Step 10

**What changes:**
- `backtest/runner.py` — new. `run(scenarios, start_date, end_date, data_dir, settings, progress_callback=None) -> tuple[pd.DataFrame, pd.DataFrame]`. Per scenario: load universe, per game build `Context` (load via `loaders.load_game`, sort trades, build `trades_time_array`, populate `open_prices`/`tipoff_prices` per team via analytics view), call `engine.run_scenario_on_game`. Flatten `Position` results to per-position rows per §"Output Schema". Aggregate by `(scenario_name, sweep_axis_*)`: count, mean ROI, win rate, mean hold, mean drawdown, forced-close count.
- Logs status breakdown including `forced_close` counts.

**Key details:**
- `sweep_axis_<name>` columns: one per sweep axis present anywhere; NaN for scenarios that don't include that axis.
- Aggregation handles favorite (baselines real) and underdog (baseline columns NaN) cases.
- **Audit existing test mocks before assertions** (HIGH-salience prior lesson).

**Test strategy:**
- `tests/test_runner.py`: 3 synthetic games × 1 dip_buy scenario with 3-sweep → 9 position rows; aggregation produces 3 rows.
- `tests/test_underdog_path.py`: full pipeline with `side_target="underdog"` — per-team trade slicing, settlement direction correct, baseline columns NaN.

---

### Step 16: Export module update for per-position schema
Files: backtest/backtest_export.py, tests/test_backtest_export.py
Depends on: Step 15

**What changes:**
- `export_backtest_results` — generic over `scenario_name` and `sweep_axis_*`. CSV/JSON exports per-position frame and aggregation frame. Heatmap dimensions user-specified instead of hardcoded `dip_threshold × exit_type`.
- Update `tests/test_backtest_export.py` for new schema; remove dropped-column assertions; add `scenario_name`/`sweep_axis_*` assertions.

**Test strategy:**
- CSV/JSON round-trip; 2D heatmap; absence of sweep axis renders 1xN row.

---

### Step 17: New UI pages
Files: pages/scenario_runner_page.py, pages/scenario_results_page.py, app.py
Depends on: Step 15, Step 16

**What changes:**
- `pages/scenario_runner_page.py` — Dash page. Lists scenarios via `scenarios.load_scenarios`. Multi-select + date range + Run. Calls `runner.run(...)` with progress callback wired to a Dash `Interval` progress bar.
- `pages/scenario_results_page.py` — per-position table + per-scenario aggregation table + sweep-axis heatmap. Reuses `backtest_export` chart helpers.
- `app.py` — register new pages. Old pages remain registered (still wired to old runner) until Step 19.

**Key details:**
- Old UI continues to work in parallel because old runner files are NOT deleted until Step 19.

**Test strategy:**
- No automated UI tests in this codebase; manual smoke documented in PR.

---

### Step 18: Rewrite CLI
Files: backtest_cli.py, tests/test_backtest_cli.py
Depends on: Step 15

**What changes:**
- `backtest_cli.py` — new flags: `--scenario <name>` (repeatable) or `--scenarios-glob <pattern>`; `--start-date`, `--end-date`, `--data-dir`, `--output <path>`. Drops old flags (`--dip-thresholds`, `--exit-type`, `--fee-model`, `--sport-filter`).
- `tests/test_backtest_cli.py` — replace old-flag tests with scenario-flag tests. Fix the pre-existing import bug (`backtest.backtest_cli` ≠ project-root `backtest_cli`).

**Test strategy:**
- Parses scenario flags; rejects unknown name; runs end-to-end on a fixture date range with `dip_buy_favorite`; output file created.

---

### Step 19: Delete old engine + old UI + docs update (gated 2-week sunset)
Files: backtest/backtest_config.py, backtest/backtest_single_game.py, backtest/backtest_runner.py, backtest/dip_entry_detection.py, backtest/backtest_universe.py, pages/backtest_runner_page.py, pages/backtest_results_page.py, tests/test_dip_entry_detection.py, tests/test_backtest_single_game.py, tests/test_backtest_runner.py, tests/test_backtest_universe.py, tests/test_backtest_config.py, app.py, CLAUDE.md, README.md
Depends on: Step 17, Step 18

**What changes:**
- Delete listed Python files and their tests.
- Remove `open_favorite_team` kwarg alias from `backtest_settlement.py` and `backtest_baselines.py` (added in Steps 5/6).
- `app.py` — drop registration of old pages.
- `CLAUDE.md` — rewrite "Backtest Framework" section in §"Structure" for new module layout.
- `README.md` — update CLI usage if present.

**Key details:**
- **Manual gate**: do not execute until 2 weeks of new-UI-only operation (per source plan §"Migration Sequence" item 7). Mark as "manual-trigger" in execute-plan.

**Test strategy:**
- Full suite passes after deletion. `grep` confirms no imports of deleted modules.

---

## Execution Preview

```
Wave 0 (3 parallel):  Step 1  — contracts/registry/scenarios skeleton
                      Step 4  — side-aware compute_trade_pnl
                      Step 5  — side-aware resolve_settlement

Wave 1 (5 parallel):  Step 2  — PositionManager
                      Step 6  — side-aware baselines
                      Step 7  — upper_strong filter port
                      Step 8  — dip_below_anchor trigger + parity
                      Step 10 — dip_buy scenario JSON + loader test

Wave 2 (4 parallel):  Step 3  — engine.py + scanner cursor tests
                      Step 9  — port four exit components
                      Step 11 — pct_drop_window trigger
                      Step 12 — first_k_above filter

Wave 3 (2 parallel):  Step 13 — tp_sl exit
                      Step 15 — runner + underdog test

Wave 4 (3 parallel):  Step 14 — two new scenario JSONs
                      Step 16 — backtest_export per-position schema
                      Step 18 — CLI rewrite

Wave 5 (1):           Step 17 — new UI pages

Wave 6 (1, manual):   Step 19 — deletions + docs (gated 2-week sunset)
```

Critical path: Step 1 → Step 2 → Step 3 → Step 15 → Step 17 → Step 19 (6 hops).
Max parallelism: 5 agents (Wave 1).

Note: Parallel execution requires a git repository with a configured remote. If unavailable, /execute-plan falls back to sequential mode.

## Risk Flags

- **Restructuring applied**: source plan §"Migration Sequence" §6 contains an in-text revision noting old UI breaks between original step 4 and step 7. Resolved by (a) keeping old runner files alive throughout Steps 1-18 (deletion is Step 19 only), and (b) adding kw alias `open_favorite_team` → `entry_team` in Steps 5/6 so old `backtest_single_game.py` keeps importing successfully. Alias removed in Step 19.
- **Shared `__init__.py` registration files** create ordering deps within sub-packages: `triggers/__init__.py` (Step 8 → 11), `exits/__init__.py` (Step 9 → 13), `filters/__init__.py` (Step 7 → 12). Captured as explicit `Depends on:` edges.
- **`Context` construction reads analytics + loaders** — Step 15 (runner) implicitly depends on `analytics.get_analytics_view`. If analytics fails, record game with `status="missing_analytics"` and skip.
- **Scanner cursor performance**: mitigated by `np.searchsorted` slicing; `tests/test_scanner_cursor.py` perf-shape assertion catches regression.
- **Mock fixture audit (HIGH-salience prior lesson)**: when implementing Step 15 aggregation, audit every per-result mock in `tests/test_runner.py`, `tests/test_backtest_baselines.py`, `tests/test_underdog_path.py` for missing fields BEFORE writing assertions.
- **Step 17 lacks automated UI tests** — Dash UI exercised via manual smoke; smoke checklist must be in PR description.
- **Step 19 gated on a calendar wall-clock (2 weeks of new-UI-only use)** — execute-plan should treat as manual-trigger.
- **Underdog scenarios bypass baselines entirely** — intentional; Step 6 + Step 15 both enforce NaN baseline columns when `side != "favorite"`.

## Verification

After Step 18 (full new engine, old engine still wired to old UI):
1. `pytest tests/ -x` — all tests pass (old + new).
2. `python backtest_cli.py --scenario dip_buy_favorite --start-date 2026-03-01 --end-date 2026-03-20 --output out.csv` — produces per-position CSV with `scenario_name` containing 3 sweep variants (`__trigger.threshold_cents=10|15|20`), `position_index_in_game >= 0` populated, `forced_close` rows present.
3. `python backtest_cli.py --scenario favorite_drop_50pct_60min_tp_sl ...` — runs to completion; output includes scale-in rows (multiple positions per game) on at least one game; `exit_kind` distribution includes `take_profit`, `stop_loss`, and `forced_close`.
4. `python app.py` → load new scenario runner page → run dip_buy_favorite over a 5-game range → both per-position table and aggregation table render. Old UI pages still render (untouched).
5. After 2-week sunset: re-run (1) post-Step 19 — suite passes, no old-module imports remain (`grep` check).
