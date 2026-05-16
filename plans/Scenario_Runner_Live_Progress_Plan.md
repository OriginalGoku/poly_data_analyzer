# Scenario Runner Live Progress Plan

> Surface per-game progress on the `/scenario-runner` page so the UI no longer appears frozen during a run.

---

## Problem Statement

The `/scenario-runner` page submits a backtest job via a background thread and polls a shared `_run_state` dict every 1s, but the UI sits on `[--------------------] 0/1 scenarios — Starting...` until the entire run completes. Root cause: `backtest/runner.py:355` invokes `progress_callback` exactly once per scenario, *after* every game in that scenario has been processed. For the typical 1-scenario, dozens-of-games run, the callback never fires until the bar would jump straight to 100%. All polling, threading, and `_run_state` plumbing already exists; only the granularity of progress emission is wrong.

## Design Decisions

### D1: Per-game counter + current-item label (no log tail)

**Decision:** Show `Scenario k/N — <name>: <date>/<match_id>` as a header line and a per-scenario bar `[####----] m/M games` below it.

**Rationale:** Directly answers "is anything happening?" without the complexity of a custom `logging.Handler` + ring-buffer + larger UI panel. User explicitly chose this option.

**Trade-off:** Rejected (a) counter + scrolling log tail and (b) full streaming log, both of which add UI/state surface area for a marginal information gain on a single-user local app.

### D2: Bar resets per scenario (games-within-current-scenario semantics)

**Decision:** The bar's `done/total` reflects games processed within the *current* scenario. Header line carries scenario-level position (`Scenario k/N`).

**Rationale:** Most informative for the typical 1-scenario run. Avoids a pre-pass to count games across all scenarios. User explicitly chose this option.

**Trade-off:** Rejected the alternative of a single monotonic bar over total games across all scenarios (would require pre-counting and adds complexity for little benefit).

### D3: Extend `progress_callback` arity rather than introduce a new channel

**Decision:** Change the callback signature from `(scen_done, scen_total, msg)` to `(scen_done, scen_total, game_done, game_total, msg)`.

**Rationale:** Reuses the existing thread-safe progress channel; no new state mechanism. Only two in-repo callers (`pages/scenario_runner_page.py:244`, `tests/test_runner.py:207`) — `backtest_cli.py` does not pass `progress_callback`, so it is unaffected.

**Trade-off:** A breaking signature change, but scope is contained to two files. Avoided keeping a backward-compatible shim because there are no external callers.

### D4: Emit "loading universe" signal before the inner game loop

**Decision:** Fire `progress_callback(scen_idx, total_scenarios, 0, len(games), f"{scenario.name}: loading universe ({len(games)} games)")` once after `games = universes_cache[cache_key]` resolves, before iterating games.

**Rationale:** When the universe filter is slow, this is the only signal the UI gets between submission and first game. Cheap to add.

**Trade-off:** None — emission is one extra call.

## Implementation Plan

### Step 1 — `backtest/runner.py`: finer-grained progress emission

Files: `backtest/runner.py`

- Change `progress_callback` type at `:317` to `Callable[[int, int, int, int, str], None]` with semantics `(scen_done, scen_total, game_done, game_total, msg)`.
- In the scenarios loop (`:336`):
  - After `games = universes_cache[cache_key]` (`:345`), emit `progress_callback(scen_idx, total, 0, len(games), f"{scenario.name}: loading universe ({len(games)} games)")`.
  - Convert inner loop to `for game_idx, gm in enumerate(games):` (`:347`). After the row-append body, emit `progress_callback(scen_idx, total, game_idx + 1, len(games), f"{scenario.name}: {gm.date}/{gm.match_id}")`.
  - Replace post-scenario emission at `:355-356` with `progress_callback(scen_idx + 1, total, len(games), len(games), f"{scenario.name}: complete")`.
- All emissions guarded by `if progress_callback is not None`.
- No behavior change to position generation, aggregation, or DataFrame outputs.
- `len(games) == 0` is allowed; pre-loop emission still fires with `game_total=0`, inner loop simply doesn't iterate.

### Step 2 — `pages/scenario_runner_page.py`: track and render per-game progress

Files: `pages/scenario_runner_page.py`

- Extend `_run_state` (`:22-29`) with `"games_done": 0, "games_total": 0`.
- In `start_run` initialization (`:170-175`), reset both new keys to 0.
- Update inner `progress_callback` at `:244-247` to the new 5-arg signature; write all four counters + msg into `_run_state`.
- In `poll_status` (`:198-209`), replace bar logic:
  - When `running` and `games_total > 0`: header `f"Scenario {min(scen_done+1, scen_total)}/{scen_total} — {msg}"`; bar `[##########----------]` filled by `int(games_done / games_total * 20)`; counter `f"{games_done}/{games_total} games"`.
  - When `running` and `games_total == 0`: render scenario header + raw `msg` only (no bar) — covers loading-universe phase and empty-universe scenarios. Avoid divide-by-zero.
  - Completion / error branches unchanged.
- No layout/component changes; `dcc.Interval` poll cadence stays at 1s.

### Step 3 — `tests/test_runner.py`: update progress-callback test

Files: `tests/test_runner.py`

- `:207` — change `progress(done, total, name)` to `progress(scen_done, scen_total, game_done, game_total, name)`.
- `:274-276` — update assertions:
  - At least one pre-loop emission and one per-game emission per scenario.
  - Final call has `scen_done == scen_total` and `game_done == game_total`.
  - `game_done` reaches `game_total` for each scenario.
- Empty-universe test (`:279+`) — if it asserts on progress, expect a pre-loop + post-scenario emission with `game_total == 0`.

## Verification

1. **Single-scenario manual run:** `python app.py`; open `/scenario-runner`; pick one scenario over a date range producing ≥10 games; click **Run Scenarios**.
   - Within ~1–2s status reads `Scenario 1/1 — <name>: loading universe (N games)`.
   - Bar advances `1/N`, `2/N`, … with the message updating to the current `date/match_id`.
   - On completion: `Run complete. Results saved to: …`.
2. **Multi-scenario run:** select 2+ scenarios; bar resets per scenario; `Scenario k/N` header increments.
3. **Empty universe:** date range with zero games — UI shows `loading universe (0 games)` then advances to the next scenario without a stuck bar.
4. **Error path:** force a runtime error in one scenario — `Run failed: …` renders, button re-enables.
5. **Tests:** `pytest tests/test_runner.py -q` passes.
6. **CLI regression:** `python backtest_cli.py --scenario <name> --start-date ... --end-date ...` still runs (no `progress_callback` passed; signature change is backward-safe).
