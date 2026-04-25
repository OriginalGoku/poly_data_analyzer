# Backtest Engine Redesign Plan

## Goal

Rip-and-replace the current single-strategy dip-buy backtester with a generic, composable strategy engine where universe filtering, triggers, and exits are independently registered components, scenarios are declared in JSON, and multiple concurrent (scale-in) positions per game are first-class.

The current dip-buy strategy becomes one *scenario* of the new engine. Single-entry semantics from the old engine are not preserved; the new engine treats every strategy as scale-in-capable.

## Non-Goals

- Quarter-clock-based triggers (wall-clock-since-tipoff only).
- Cross-game capital allocation / portfolio metrics.
- Multi-sport validation beyond NBA in this refactor (engine stays sport-agnostic).
- Row-level parity with old engine output (dropped — old engine forced single-entry; new engine permits scale-in).

## Locked Design Decisions

| Concern | Resolution |
|---|---|
| Migration style | Rip-and-replace. Old `backtest_config.py`, `backtest_single_game.py`, `backtest_runner.py`, `dip_entry_detection.py`, `backtest_universe.py` deleted at end of migration. Old UI pages deleted 2 weeks after new UI ships and is sole UI in use. |
| Registry shape | Three per-stage registries: `UNIVERSE_FILTERS`, `TRIGGERS`, `EXITS`. No `SIDE_SELECTORS` (side declared by trigger or universe filter output). No monolithic `Strategy` class. |
| Side support | Native per-team trade stream from `loaders.py`. No `1 − favorite_price` reconstruction. `Trigger.team` / `Trigger.token_id` / `Trigger.side` are canonical; PnL, settlement, baseline, and trade filtering all key off them. |
| Settlement | `resolve_settlement` accepts `entry_team` instead of `open_favorite_team`. |
| Baselines | Run only when `Trigger.side == "favorite"`; skipped otherwise (no fake-rebuild). |
| Scale-in | First-class. `PositionManager` owns lock policy. Two modes: `sequential` (max one open position; cool-down) and `scale_in` (multiple concurrent positions up to `max_entries`, with min-spacing). |
| Exit invariant | Every `Exit` has a real `exit_time` timestamp. No-fill cases force-close at `game_end` with `status: "forced_close"`. |
| Scanner mechanics | All triggers/exits take `(ctx, after_time, params)` and slice `trades_df` via `pd.searchsorted` on a pre-sorted datetime array stored in `Context`. No re-filtering per call. |
| Output granularity | One row per position. `position_index_in_game` column distinguishes scale-in entries within the same game. |
| Settings storage | `backtest/scenarios/*.json` directory; loader globs and merges into one scenario registry. |
| Sweep semantics | Any leaf value `{"sweep": [...]}` expands a scenario into N concrete scenarios named `<scenario>__<param_path>=<value>`. Cartesian over multiple sweep leaves. Each concrete scenario gets its own aggregation row. |
| Acceptance gates | (a) Dip-buy scenario produces identical *trigger fire times* and *exit decisions* on a fixed fixture vs. existing `find_dip_entry`/`find_exit` (unit-level, not row-level). (b) Wall-clock-windowed favorite-drop TP/SL scenarios run end-to-end with scale-in. |

## New Module Layout

```
backtest/
  __init__.py
  contracts.py              Frozen dataclasses: Context, Trigger, Exit, Position, Scenario
  registry.py               UNIVERSE_FILTERS, TRIGGERS, EXITS dicts
  scenarios.py              Scenario loader + sweep expansion (globs backtest/scenarios/*.json)
  position_manager.py       Lock/cool-down/max-entries/scale-in policy
  engine.py                 Per-game loop; runs one scenario on one game; force-close at game_end
  runner.py                 Grid orchestration: scenarios × universe -> per-position result rows

  filters/
    __init__.py             Imports register into UNIVERSE_FILTERS
    upper_strong.py         Ports current filter_upper_strong_universe
    first_k_above.py        New: first K trades after tipoff above price threshold

  triggers/
    __init__.py             Imports register into TRIGGERS
    dip_below_anchor.py     Ports find_dip_entry
    pct_drop_window.py      New: % drop with optional wall-clock window (window None = unbounded)

  exits/
    __init__.py             Imports register into EXITS
    settlement.py           Wraps resolve_settlement
    reversion_to_open.py    Ports current
    reversion_to_partial.py Ports current
    fixed_profit.py         Ports current
    tp_sl.py                New: take_profit_cents + stop_loss_cents + max_hold_seconds

  scenarios/                JSON scenario library (globbed by scenarios.py)
    dip_buy_favorite.json
    favorite_drop_50pct_60min_tp_sl.json
    favorite_drop_50pct_unbounded_tp_sl.json

  # Preserved (modified minimally):
  backtest_pnl.py           entry dict gains team/token_id/side fields
  backtest_settlement.py    Param renamed: open_favorite_team -> entry_team
  backtest_baselines.py     Skip when side != "favorite"; consume entry_team
  backtest_export.py        Generic over scenario_name + sweep axis labels
```

## Core Data Contracts (`contracts.py`)

```
Context (frozen)
  trades_df: pd.DataFrame
  trades_time_array: np.ndarray         # sorted datetime values for searchsorted
  events: list
  manifest: dict
  tipoff_time: pd.Timestamp
  game_end: pd.Timestamp
  sport: str
  open_prices: dict[str, float]         # team -> open price
  tipoff_prices: dict[str, float]       # team -> tipoff price
  favorite_team: str
  underdog_team: str
  scenario: Scenario
  settings: ChartSettings

Trigger (frozen)
  team: str
  token_id: int
  side: Literal["favorite", "underdog"]
  trigger_time: pd.Timestamp
  entry_price: float
  anchor_price: float
  reason: str

Exit (frozen)
  exit_time: pd.Timestamp               # NEVER None
  exit_price: float
  exit_kind: Literal["take_profit", "stop_loss", "reversion", "settlement", "forced_close", "max_hold"]
  status: Literal["filled", "forced_close"]

Position
  trigger: Trigger
  exit: Exit | None                     # None while open
  pnl: dict | None                      # populated post-exit
  position_index_in_game: int

Scenario (frozen)
  name: str
  description: str
  universe_filter: ComponentSpec        # name + params
  side_target: Literal["favorite", "underdog", "either"]
  trigger: ComponentSpec
  exit: ComponentSpec
  lock: LockSpec
  fee_model: Literal["taker", "maker"]
  sweep_axes: dict[str, Any]            # for output labeling

LockSpec (frozen)
  mode: Literal["sequential", "scale_in"]
  max_entries: int
  cool_down_seconds: int                # sequential: gap after exit; scale_in: min spacing between entries
  allow_re_arm_after_stop_loss: bool    # sequential only
```

## Position Manager (`position_manager.py`)

Owns all open positions for one game. Decides admission of new triggers and runs exit scanners on each tick.

API:
- `can_open(now: Timestamp) -> bool`
- `register_position(pos: Position)`
- `tick(ctx: Context, now: Timestamp)` — runs each open position's exit scanner; closes those whose exit fires.
- `next_eligible_time(now, game_end) -> Timestamp`
- `force_close_all(at: Timestamp)` — forced-close every still-open position at `at` with `status="forced_close"`, `exit_kind="forced_close"`.
- `exhausted() -> bool` — `total_entries >= max_entries` and no open positions awaiting exit.

Mode behavior:
- `sequential`: at most one open position. After a position closes, gate `can_open` with `now >= last_exit_time + cool_down_seconds`. If `allow_re_arm_after_stop_loss=False`, additionally block re-entry when last exit had `exit_kind="stop_loss"`.
- `scale_in`: up to `max_entries` concurrent. `can_open` gated only by `now >= last_entry_time + cool_down_seconds` and `len(open_positions) + closed_count < max_entries`.

## Engine Loop (`engine.py`)

```
def run_scenario_on_game(scenario, ctx) -> list[Position]:
    pm = PositionManager(scenario.lock)
    positions = []
    cursor = ctx.tipoff_time
    trigger_fn = TRIGGERS[scenario.trigger.name]
    exit_factory = EXITS[scenario.exit.name]

    while cursor < ctx.game_end and not pm.exhausted():
        pm.tick(ctx, cursor)
        if not pm.can_open(cursor):
            cursor = pm.next_eligible_time(cursor, ctx.game_end)
            continue
        trigger = trigger_fn(ctx, cursor, scenario.trigger.params)
        if trigger is None:
            break
        idx = len(positions)
        pos = Position(trigger=trigger, exit=None, pnl=None, position_index_in_game=idx)
        pm.register_position(pos, exit_scanner=exit_factory(ctx, trigger, scenario.exit.params))
        positions.append(pos)
        cursor = trigger.trigger_time + pd.Timedelta(microseconds=1)

    pm.force_close_all(ctx.game_end)

    for pos in positions:
        settlement = resolve_settlement(ctx.manifest, ctx.events, ctx.trades_df,
                                        ctx.game_end, ctx.sport, ctx.settings,
                                        entry_team=pos.trigger.team)
        pos.pnl = compute_trade_pnl(
            entry={"entry_time": pos.trigger.trigger_time,
                   "entry_price": pos.trigger.entry_price,
                   "team": pos.trigger.team,
                   "token_id": pos.trigger.token_id,
                   "side": pos.trigger.side},
            exit_={"exit_time": pos.exit.exit_time,
                   "exit_price": pos.exit.exit_price,
                   "exit_type": pos.exit.exit_kind,
                   "status": pos.exit.status,
                   "hold_seconds": int((pos.exit.exit_time - pos.trigger.trigger_time).total_seconds())},
            settlement=settlement,
            fee_model=scenario.fee_model,
            fee_pct=fee_pct_for(scenario.fee_model),
            settings=ctx.settings,
        )
    return positions
```

## Scanner Cursor Mechanics

`Context.trades_time_array` is a sorted numpy datetime array built once per game in `Context` construction. All triggers and exits convert `after_time` to an array index via `np.searchsorted(trades_time_array, after_time, side="right")` and slice `trades_df.iloc[idx:]` for downstream work. No `trades_df[trades_df["datetime"] > t]` re-filtering inside the per-tick loop.

`Context` exposes a helper:
```
def slice_after(self, after_time, team=None) -> pd.DataFrame
```
that combines the searchsorted slice with optional team filter and returns a view.

## Component Registries (`registry.py`)

```python
UNIVERSE_FILTERS: dict[str, Callable[[GameMeta, dict], bool]] = {}
TRIGGERS:        dict[str, Callable[[Context, pd.Timestamp, dict], Trigger | None]] = {}
EXITS:           dict[str, Callable[[Context, Trigger, dict], ExitScanner]] = {}
```

`ExitScanner` has signature `scan(ctx, now) -> Exit | None`. PositionManager calls it on each tick; first non-None result closes the position. Force-close at game_end synthesizes an `Exit` with `exit_kind="forced_close"` regardless of scanner state.

Registration is via explicit imports in `filters/__init__.py`, `triggers/__init__.py`, `exits/__init__.py`. No decorators, no discovery.

## Scenario JSON Schema (examples)

`backtest/scenarios/dip_buy_favorite.json`:
```json
{
  "name": "dip_buy_favorite",
  "description": "Reproduces dip-buy logic on the favorite side",
  "universe_filter": {
    "name": "upper_strong",
    "params": {"min_open_favorite_price": 0.85}
  },
  "side_target": "favorite",
  "trigger": {
    "name": "dip_below_anchor",
    "params": {
      "anchor": "open",
      "threshold_cents": {"sweep": [10, 15, 20]}
    }
  },
  "exit": {
    "name": "settlement",
    "params": {}
  },
  "lock": {
    "mode": "scale_in",
    "max_entries": 5,
    "cool_down_seconds": 0,
    "allow_re_arm_after_stop_loss": true
  },
  "fee_model": "taker"
}
```

`backtest/scenarios/favorite_drop_50pct_60min_tp_sl.json`:
```json
{
  "name": "favorite_drop_50pct_60min_tp_sl",
  "description": "Wall-clock 60-min window favorite-drop with TP/SL and scale-in",
  "universe_filter": {
    "name": "first_k_above",
    "params": {"k": 5, "min_price": 0.80}
  },
  "side_target": "favorite",
  "trigger": {
    "name": "pct_drop_window",
    "params": {
      "anchor": "open",
      "drop_pct": 50.0,
      "window_seconds_after_tipoff": [0, 3600]
    }
  },
  "exit": {
    "name": "tp_sl",
    "params": {
      "take_profit_cents": 10,
      "stop_loss_cents": 10,
      "max_hold_seconds": 3600
    }
  },
  "lock": {
    "mode": "scale_in",
    "max_entries": 3,
    "cool_down_seconds": 60,
    "allow_re_arm_after_stop_loss": true
  },
  "fee_model": "taker"
}
```

`backtest/scenarios/favorite_drop_50pct_unbounded_tp_sl.json`:
Same as above but `"window_seconds_after_tipoff": null` (unbounded — entire post-tipoff period eligible) and `"max_hold_seconds": null` (no max hold).

Sweep expansion produces concrete scenario names like `dip_buy_favorite__trigger.threshold_cents=10`, `dip_buy_favorite__trigger.threshold_cents=15`, etc.

## Output Schema

One row per `Position`. Columns:

```
scenario_name
sweep_axis_<axis_name>          (one column per sweep axis, NaN if not part of a sweep)
date, match_id, sport
side, team, token_id
anchor_price
entry_time, entry_price, entry_reason
exit_time, exit_price, exit_kind, status
gross_pnl_cents, net_pnl_cents, roi_pct, hold_seconds
true_pnl_cents, settlement_method, settlement_occurred
max_drawdown_cents
baseline_buy_at_open_roi, baseline_buy_at_tip_roi, baseline_buy_first_ingame_roi   (NaN if side != "favorite")
position_index_in_game
fee_model
```

Aggregation groups by `(scenario_name, sweep_axis_*)`: count, mean ROI, win rate, mean hold, mean drawdown, forced-close count.

## Migration Sequence

1. **Skeleton + position manager.** Land `contracts.py`, `registry.py`, `scenarios.py`, `position_manager.py`, `engine.py` with empty registries. Acceptance: imports work; new unit tests for `PositionManager` (sequential, scale-in, cool-down, max-entries, force-close, allow_re_arm_after_stop_loss) pass.

2. **Side-aware contract changes to preserved modules.**
   - `compute_trade_pnl`: entry dict gains `team`, `token_id`, `side`.
   - `resolve_settlement`: parameter renamed `open_favorite_team` → `entry_team`.
   - `backtest_baselines.py`: each baseline accepts `entry_team`, returns NaN-shaped result when called for non-favorite side.
   - Acceptance: existing `test_backtest_pnl.py`, `test_backtest_settlement.py`, `test_backtest_baselines.py` pass after mechanical signature updates. No logic regressions.

3. **Port existing components to registries.**
   - `filters/upper_strong.py` (port `filter_upper_strong_universe`).
   - `triggers/dip_below_anchor.py` (port `find_dip_entry` to scanner shape).
   - `exits/settlement.py`, `exits/reversion_to_open.py`, `exits/reversion_to_partial.py`, `exits/fixed_profit.py` (port from `find_exit` branches).
   - Acceptance: new unit tests per component using existing fixtures from `tests/test_dip_entry_detection.py`. Trigger fire times and exit decisions match old implementation on fixture inputs (component-level parity, decoupled from lock policy).

4. **Scenario loader + engine wired.** `scenarios.py` globs `backtest/scenarios/*.json`, parses, expands sweeps. `runner.py` orchestrates `(scenarios × universe games)` via `engine.run_scenario_on_game`, emits per-position rows. Acceptance: `dip_buy_favorite` scenario runs over a 20-game NBA fixture; emits per-position rows; status counts include `forced_close`; sweep expansion produces 3 concrete scenarios for `threshold_cents`.

5. **New components for second acceptance scenario.**
   - `filters/first_k_above.py`: filter games where first K post-tipoff trades on the favorite side are all above a price threshold.
   - `triggers/pct_drop_window.py`: scan favorite trades for first trade where price has dropped `drop_pct` from anchor, optionally bounded to wall-clock window after tipoff (None = unbounded).
   - `exits/tp_sl.py`: take-profit at `entry + take_profit_cents/100`, stop-loss at `entry − stop_loss_cents/100`, max-hold at `entry_time + max_hold_seconds` (None = no max hold). First condition wins.
   - Acceptance: `favorite_drop_50pct_60min_tp_sl.json` and `favorite_drop_50pct_unbounded_tp_sl.json` both run end-to-end on a 20-game NBA fixture; produce non-empty position output; scale-in produces multiple concurrent positions on at least one game; forced-close paths trigger on at least one position; per-position rows include all expected columns.

6. **New UI pages.** `pages/scenario_runner_page.py`, `pages/scenario_results_page.py` reading scenario JSON files and new per-position result schema. Old pages remain wired to the old (still-deleted) modules — no, old pages will already be broken at this point since old runner is gone. Therefore: new UI pages must ship **alongside** step 4, not after.

   *Revised ordering*: between step 4 and step 5, ship new UI pages so the new engine is usable. Old UI continues to import the not-yet-deleted old runner. Wait — old runner is deleted in step 7. So old UI is broken between step 4 and step 7. Compromise: in step 4, *also* keep old runner files in place (don't delete) so old UI keeps working. New UI ships in parallel. Step 7 deletes old code only after 2 weeks of new-UI-only use.

   Acceptance: new UI lists scenarios from JSON, runs selected scenario(s), renders per-position table + per-scenario aggregation table.

7. **Deletion (gated by 2 weeks of new-UI-only use).**
   - Delete `backtest/backtest_config.py`, `backtest/backtest_single_game.py`, `backtest/backtest_runner.py`, `backtest/dip_entry_detection.py`, `backtest/backtest_universe.py`.
   - Delete `pages/backtest_runner_page.py`, `pages/backtest_results_page.py`.
   - Delete tests targeting deleted modules: `test_dip_entry_detection.py`, `test_backtest_single_game.py` (old), `test_backtest_runner.py` (old), `test_backtest_universe.py` (old).
   - Update `backtest_cli.py` to drive the new engine via scenario name(s).

## Test Plan

### Kept passing throughout migration
- `tests/test_backtest_pnl.py` (mechanical signature updates only)
- `tests/test_backtest_settlement.py` (mechanical signature updates only)
- `tests/test_backtest_baselines.py` (mechanical signature updates only)
- `tests/test_backtest_export.py` (export module updates for new schema)

### Net new
- `tests/test_position_manager.py`: sequential vs scale_in, cool-down gating, max_entries cap, force_close_all, allow_re_arm_after_stop_loss.
- `tests/test_forced_close_invariant.py`: every Exit produced by every code path has a real `exit_time`.
- `tests/test_scenarios_loader.py`: JSON parse, sweep expansion (empty list, single value, multi-axis cartesian), schema validation errors, scenario-name uniqueness across files.
- `tests/test_engine.py`: full per-game loop on synthetic trade streams; verifies cursor advance, scale-in produces multiple positions, sequential blocks until exit, forced-close at game_end populates remaining positions.
- `tests/test_filters_upper_strong.py`: ports `test_backtest_universe.py` cases.
- `tests/test_filters_first_k_above.py`: K-trade window edge cases (fewer than K trades, exactly K, mix of above/below threshold).
- `tests/test_triggers_dip_below_anchor.py`: ports relevant cases from `test_dip_entry_detection.py`.
- `tests/test_triggers_pct_drop_window.py`: bounded-window edge cases; unbounded equivalence; anchor switching; never-fires path.
- `tests/test_exits_*.py`: one file per exit, ports relevant cases from `test_dip_entry_detection.py`.
- `tests/test_exits_tp_sl.py`: take_profit-first, stop_loss-first, max_hold-first, none-fire (forced_close path), simultaneous TP/SL on same trade.
- `tests/test_underdog_path.py`: full pipeline with `side_target="underdog"`; settlement direction correct; baselines NaN; per-team trade slicing correct.
- `tests/test_runner.py`: scenarios × universe orchestration; sweep produces N concrete-scenario aggregation rows; status breakdown correct.
- `tests/test_scanner_cursor.py`: searchsorted slice correctness across edge timestamps; performance check (N triggers should not be O(N²) in trade count).

### Component-level parity gate (replaces row-level parity)
- `tests/test_dip_buy_component_parity.py`: on a fixed fixture (5 games saved as JSON), the new `dip_below_anchor` trigger fires at exactly the same `(timestamp, price)` pairs as old `find_dip_entry`; new `settlement` exit produces the same exit timestamps as old `find_exit(exit_type="settlement")`. Lock-policy-independent.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Old UI broken between step 4 and step 7 | Keep old runner files in place until step 7; old UI continues to function during overlap. |
| Scanner re-filtering becomes O(N·M) on dense feeds with many entries | `Context.trades_time_array` + `searchsorted` slicing in every trigger/exit. `tests/test_scanner_cursor.py` exercises performance shape. |
| Forced-close trades silently distort PnL distributions | `exit_kind="forced_close"` is a distinct value; runner reports forced-close count per scenario in aggregation; output schema preserves it. |
| Scale-in with stop-loss exits and `allow_re_arm_after_stop_loss=False` ambiguous | Documented: in scale-in mode, `allow_re_arm_after_stop_loss` is ignored (only meaningful for sequential). Validated in PositionManager constructor with warning if set with `scale_in`. |
| Sweep block in JSON conflicts with literal list values | `{"sweep": [...]}` is the only sweep marker; bare lists are treated as literal list params. Loader validates. |
| Old tests deleted before parity established | Step 7 (deletions) gated on 2 weeks of new-UI-only use; component parity test from step 3 covers regression risk for trigger/exit logic. |

## Final Deliverables

1. New `backtest/` module structure as specified.
2. Side-aware updates to `backtest_pnl.py`, `backtest_settlement.py`, `backtest_baselines.py`, `backtest_export.py`.
3. Three scenario JSON files: `dip_buy_favorite.json`, `favorite_drop_50pct_60min_tp_sl.json`, `favorite_drop_50pct_unbounded_tp_sl.json`.
4. New UI pages: `pages/scenario_runner_page.py`, `pages/scenario_results_page.py`.
5. New CLI: `backtest_cli.py` rewritten to take scenario name(s) and date range.
6. Test suite as specified.
7. Updated docs: `CLAUDE.md` backtest-framework section, `ARCHITECTURE.md` if it covers backtest, README backtest commands.
8. Step 7 deletions executed only after 2-week new-UI-only window.
