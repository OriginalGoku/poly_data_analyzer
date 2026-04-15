# Backtest Correctness Fixes Plan

> Fix six confirmed bugs in the backtest engine: look-ahead bias in exits, zero-PnL silent losses, one-sided fee, gross/net ROI confusion, broken time_based_quarter (removed), and baseline fee model mismatch.

---

## Problem Statement

A full audit of the backtesting framework surfaced four critical correctness issues and two medium issues. All bugs produce systematically wrong financial results, ranging from overstated ROI to data leakage via post-settlement price spikes. The fixes are scoped to files under `backtest/` and their tests. No UI changes are required.

---

## Design Decisions

### D1: Not-triggered exits use forced-close at last in-game price

**Decision:** When a non-settlement exit condition (reversion_to_open, reversion_to_partial, fixed_profit) is never met, fall back to the last in-game trade before game_end as the exit price with `status="forced_close"`, rather than recording 0 PnL.

**Rationale:** Recording 0 ROI for a position that was never exited silently hides losses and biases the ROI mean toward zero. A forced-close at the last available in-game price is the realistic simulation of being closed out at market end.

**Trade-off:** Excluding not-triggered exits from the ROI mean entirely was considered. Rejected because it introduces selection bias (only measuring "winning" trades that reached their target).

### D2: Remove time_based_quarter entirely

**Decision:** Delete the `time_based_quarter` exit type from `find_exit()`, remove it from the `DipBuyBacktestConfig` Literal, and delete all associated config fields (`time_exit_checkpoint`, `nba_quarter_duration_min`, `nhl_period_duration_min`, `mlb_inning_duration_min`).

**Rationale:** The exit type had three compounding bugs: wrong `exit_param` type passed at the call site, `time_exit_checkpoint` never plumbed anywhere, and `settings.nba_quarter_duration_min` doesn't exist on `ChartSettings` causing a crash. It was untested in real runs and not exposed in the UI.

**Trade-off:** Fully fixing the exit type was considered. Rejected because it required significant plumbing for a feature with no current users.

### D3: Two-sided fee applies to all compute_trade_pnl() callers

**Decision:** Change `fee_cost = exit_price * fee_pct * 100` to `fee_cost = (entry_price + exit_price) * fee_pct * 100`.

**Rationale:** Polymarket charges taker fee on both buy (entry) and sell (exit). The previous one-sided fee systematically overstated net ROI.

**Trade-off:** Changing the ROI denominator to include entry fee was considered. Rejected — the magnitude is below practical decision threshold (<0.2%) and would require display-layer updates.

---

## Implementation Plan

### Step 1: Fix find_exit() — game_end bound and forced-close fallback
Files: `backtest/dip_entry_detection.py`

- At the start of `find_exit()`, change `post_entry` to add `& (trades_df["datetime"] < game_end)`. This prevents post-settlement price spikes (0.0/1.0 resolution prints) from triggering non-settlement exits.
- For `reversion_to_open`, `reversion_to_partial`, and `fixed_profit` branches: when the target is never met, if `post_entry.empty` return `status="not_triggered"` with `exit_price=None`; otherwise return the last in-game trade as `status="forced_close"`.
- The `settlement` branch is unchanged (already correctly bounded).
- Do NOT remove the `settings` parameter yet — defer to Step 3.

### Step 2: Apply two-sided fee to compute_trade_pnl()
Files: `backtest/backtest_pnl.py`

- Change line 41: `fee_cost = exit_price * fee_pct * 100` → `fee_cost = (entry_price + exit_price) * fee_pct * 100`
- When `exit_price is None`, the existing `fee_cost = 0` branch remains (degenerate case with no realised exit).
- `true_pnl_cents` (settlement oracle metric) remains fee-free by design.

### Step 3: Remove time_based_quarter exit type
Files: `backtest/dip_entry_detection.py`, `backtest/backtest_config.py`, `backtest/backtest_runner.py`

- `dip_entry_detection.py`: delete the `elif exit_type == "time_based_quarter":` block, remove `"time_based_quarter"` from the `exit_type` Literal annotation, remove the `settings` parameter from `find_exit()` signature entirely, update docstring.
- `backtest_config.py`: remove `time_exit_checkpoint`, `nba_quarter_duration_min`, `nhl_period_duration_min`, `mlb_inning_duration_min` fields and their `__post_init__` validation; remove `"time_based_quarter"` from `exit_type` Literal; update docstring.
- `backtest_runner.py`: in the `DipBuyBacktestConfig(...)` construction inside `run_backtest_grid()`, remove `time_exit_checkpoint=config.time_exit_checkpoint,`, `nba_quarter_duration_min=config.nba_quarter_duration_min,`, and `nhl_period_duration_min=config.nhl_period_duration_min,`.
- `backtest_cli.py` needs no changes; passing `time_based_quarter` via CLI will now fail at config validation with a clear error.

### Step 4: Pass fee_model to baseline functions and update single_game.py callers
Files: `backtest/backtest_baselines.py`, `backtest/backtest_single_game.py`

- `backtest_baselines.py`: add `fee_model: str = "taker"` parameter to all three baseline functions (`baseline_buy_at_open`, `baseline_buy_at_tipoff`, `baseline_buy_first_ingame`). Change `compute_trade_pnl(fee_model="taker", ...)` to `compute_trade_pnl(fee_model=fee_model, ...)` in each.
- `backtest_single_game.py`:
  - Remove `settings=None` from the `find_exit()` call (Step 3 removed the param from the signature).
  - Add `fee_model=config.fee_model` to all three baseline calls.

### Step 5: Fix gross_roi_mean in aggregation
Files: `backtest/backtest_runner.py`

- Change line 191:
  ```python
  "gross_roi_mean": trades_with_entry["roi_pct"].mean() if len(trades_with_entry) > 0 else 0,
  ```
  to:
  ```python
  "gross_roi_mean": (
      (trades_with_entry["gross_pnl_cents"] / (trades_with_entry["entry_price"] * 100)).mean()
      if len(trades_with_entry) > 0 else 0
  ),
  ```
- Line 192 (`net_roi_mean`) is unchanged — `roi_pct` is correctly net.

### Step 6: Update all test files
Files: `tests/test_dip_entry_detection.py`, `tests/test_backtest_pnl.py`, `tests/test_backtest_baselines.py`, `tests/test_backtest_runner.py`, `tests/test_backtest_config.py`

**test_dip_entry_detection.py:**
- Remove `mock_settings` fixture and all `settings=mock_settings` arguments from `find_exit()` calls.
- Delete `test_find_exit_time_based_nba` and `test_find_exit_time_based_non_nba`.
- Update `test_find_exit_not_triggered`: now expects `status="forced_close"` and a non-None `exit_price` (the last in-game trade).
- Add `test_find_exit_forced_close_no_post_trades`: all trades before entry_time → `status="not_triggered"`, `exit_price=None`.
- Add `test_find_exit_post_game_trade_excluded`: trades after `game_end` spiking to 1.0 do not trigger exit.

**test_backtest_pnl.py:**
- Update `test_compute_pnl_profitable_with_taker_fee`: fee was `0.82 * 0.002 * 100 = 0.164`; now `(0.80 + 0.82) * 0.002 * 100 = 0.324`. Update `net_pnl_cents` and `fee_cost_cents` assertions.
- Update `test_compute_pnl_loss`: recalculate expected fee amount.

**test_backtest_baselines.py:**
- Add `fee_model="taker"` to all baseline calls.
- Update fee-dependent assertions to reflect two-sided fee.
- Add `test_baseline_buy_at_open_maker_fee`: pass `fee_model="maker"`, assert `fee_cost_cents == 0.0`.

**test_backtest_config.py:**
- Remove tests for `time_exit_checkpoint`, `nba_quarter_duration_min` validation, and `"time_based_quarter"` as a valid exit_type.

**test_backtest_runner.py:**
- Add assertion: `gross_roi_mean != net_roi_mean` when `fee_pct > 0`.
- Add case verifying `gross_roi_mean > net_roi_mean` for a profitable trade.

---

## Execution Order (Wave Groups)

```
Wave 0 (parallel): Step 1, Step 2
Wave 1:            Step 3  (shares dip_entry_detection.py with Step 1)
Wave 2 (parallel): Step 4, Step 5  (Step 4 shares single_game.py; Step 5 shares runner.py with Step 3)
Wave 3:            Step 6  (tests for all prior steps)
```

Critical path: Step 1 → Step 3 → Step 4 → Step 6 (4 waves)

---

## Verification

```bash
python -m pytest tests/ -v                             # full suite, zero failures
python -m pytest tests/test_backtest_pnl.py -v        # fee calculation correctness
python -m pytest tests/test_dip_entry_detection.py -v # forced-close + game_end bound
python -m pytest tests/test_backtest_runner.py -v     # gross != net ROI assertion
```

End-to-end sanity (small CLI run):
1. `gross_roi_mean` and `net_roi_mean` columns differ in CSV output.
2. `forced_close` appears as a status value in per_game results for non-settlement exits.
3. `time_based_quarter` passed as `--exit-types` fails with a clear validation error.
4. Very few (or zero) `not_triggered` rows with non-null `entry_price` in per_game CSV.
