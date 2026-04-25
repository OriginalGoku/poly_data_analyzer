# Backtest Engine Redesign — Step 19 (Sunset)

> **Status:** Steps 1–18 executed and merged on 2026-04-25. This file holds only the gated sunset deletion (Step 19). The full original plan is archived at `executed_plans/Backtest_Engine_Redesign_Technical_Plan_steps_1-18.md`.

---

## Sunset Gate

**Earliest execution date: 2026-05-09** (14 days after the new engine landed on `main`).

Do not run this step until **all** of the following are true:

1. **Calendar:** ≥14 days have passed since 2026-04-25.
2. **New UI used in production:** the user has actually run scenarios through `/scenario-runner` and `/scenario-results` over a non-trivial date range, and confirmed results look correct.
3. **Old UI confirmed unused:** `pages/backtest_runner_page.py` and `pages/backtest_results_page.py` have not been opened in normal workflow during the sunset window. (User judgment — no automated check.)
4. **No outstanding regressions:** running `python -m pytest tests -q --tb=no` shows the same 13 pre-existing failures from the post-plan baseline (or fewer); no new failures introduced by downstream work.
5. **No external consumers:** confirm no scripts, notebooks, or cron jobs outside this repo import the modules slated for deletion (`backtest_single_game`, `run_backtest_grid`, `find_dip_entry`, `find_exit`, `filter_upper_strong_universe`, `DipBuyBacktestConfig`).

If any of the above are not met, **defer**. The cost of premature deletion is high; the cost of waiting another week is zero.

---

## Step 19: Delete old engine + old UI + docs update

**Files (delete unless noted):**
- `backtest/backtest_config.py` (delete)
- `backtest/backtest_single_game.py` (delete)
- `backtest/backtest_runner.py` (delete)
- `backtest/dip_entry_detection.py` (delete)
- `backtest/backtest_universe.py` (delete)
- `pages/backtest_runner_page.py` (delete)
- `pages/backtest_results_page.py` (delete)
- `tests/test_dip_entry_detection.py` (delete)
- `tests/test_backtest_single_game.py` (delete)
- `tests/test_backtest_runner.py` (delete)
- `tests/test_backtest_universe.py` (delete)
- `tests/test_backtest_config.py` (delete)
- `backtest/__init__.py` (modify — drop legacy exports)
- `backtest/backtest_settlement.py` (modify — remove `open_favorite_team` kwarg alias)
- `backtest/backtest_baselines.py` (modify — remove `open_favorite_team` kwarg alias)
- `app.py` (modify — drop registration of old pages)
- `CLAUDE.md` (modify — remove "legacy" subsection in §"Structure → Backtest Framework")
- `ARCHITECTURE.md` (modify — remove "Legacy: Dip-Buy Framework" section, promote "New Scenario-Driven Backtest Engine" to top of Backtest Framework)
- `README.md` (modify — remove legacy CLI/usage references; keep new scenario CLI section only)

**Depends on:** Steps 17, 18 (already merged).

---

## Pre-Flight Checklist

Run before starting Step 19:

```bash
# 1. Confirm no production importer of the deleted symbols
grep -rn "from backtest.backtest_config" --include="*.py" .
grep -rn "from backtest.backtest_single_game" --include="*.py" .
grep -rn "from backtest.backtest_runner" --include="*.py" .
grep -rn "from backtest.dip_entry_detection" --include="*.py" .
grep -rn "from backtest.backtest_universe" --include="*.py" .
grep -rn "DipBuyBacktestConfig\|backtest_single_game\|run_backtest_grid\|find_dip_entry\|find_exit\|filter_upper_strong_universe" --include="*.py" .

# 2. Confirm `open_favorite_team` alias has no live callers
grep -rn "open_favorite_team" --include="*.py" .

# 3. Snapshot current test state
python -m pytest tests -q --tb=no 2>&1 | tail -3
```

The greps should return matches **only** inside the files slated for deletion (and the alias keyword definition itself in `backtest_settlement.py` / `backtest_baselines.py`). If anything else hits, investigate before deleting.

---

## Implementation Sequence

1. **Delete the listed files** (`git rm` each).
2. **Trim `backtest/__init__.py`** — remove the legacy imports and `__all__` entries:
   - `DipBuyBacktestConfig`, `filter_upper_strong_universe`, `find_dip_entry`, `find_exit`, `baseline_*` (keep), `backtest_single_game`, `run_backtest_grid`. Keep the new contracts/registries/loaders.
3. **Remove `open_favorite_team` alias** in `backtest/backtest_settlement.py::resolve_settlement` — drop the alias kwarg, the TypeError-on-both check, and the alias-only test cases (the alias-test cases were intentionally retained in Step 5; remove now).
4. **Remove `open_favorite_team` alias** in `backtest/backtest_baselines.py` — same pattern.
5. **`app.py`** — drop the two old `register_page` (or equivalent) calls. Confirm `/scenario-runner` and `/scenario-results` are still registered.
6. **Docs** — see `Files` above for which sections to trim. Goal: docs describe only the new engine.
7. **Run full suite:** `python -m pytest tests -q --tb=no`. Expected:
   - All 13 pre-existing failures listed in the post-plan baseline are gone (the test files containing them are deleted).
   - Total pass count drops by ~4 (the 4 `test_backtest_single_game` tests that were failing) plus whatever was passing in the deleted test files.
   - **No new failures.**
8. **Final import sweep:** re-run the greps from the pre-flight checklist. All should return zero matches now.

---

## Test Strategy

- Full suite passes after deletion.
- `grep` confirms no imports of deleted modules anywhere in the repo.
- Manual: `python app.py` boots; `/scenario-runner` + `/scenario-results` render; old `/backtest-runner` and `/backtest-results` URLs return 404 (or whatever Dash does for unregistered pages).
- CLI: `python backtest_cli.py --scenario dip_buy_favorite --start-date 2026-03-01 --end-date 2026-03-20 --output /tmp/sunset_check` produces output dir without error.

---

## Risk Flags

- **Hidden importers in scratch notebooks / one-off scripts.** Pre-flight grep covers tracked files only. If you maintain ad-hoc scripts outside the repo, audit them too.
- **External consumers of the public `backtest` API.** If anything imports `from backtest import DipBuyBacktestConfig` (or the other dropped symbols), it will break at import time after the `__init__.py` trim. Surface via the pre-flight grep.
- **Doc drift.** ARCHITECTURE.md and CLAUDE.md currently carry both the legacy and new sections. Be deliberate about which prose survives — the new sections were written assuming the legacy ones would be removed, so don't merge them mechanically; reread for coherence.
- **Test count optics.** Suite size shrinks because deleted test files are gone — that is expected, not a regression. Track only the *failure* count, not the pass count, when comparing baselines.

---

## Verification (post-execution)

1. `python -m pytest tests -q --tb=no` — full suite passes; no failures except possibly the 2 unrelated pre-existing failures (`test_nba_analysis::test_summary_and_grouped_outcome_metrics_handle_missing_coverage`, `test_sensitivity::TestSensitivityCache::test_cache_read_accepts_mixed_iso_timestamp_formats`). Those are unrelated to this plan and should be triaged separately.
2. `grep -rn "from backtest.backtest_single_game\|from backtest.backtest_runner\|from backtest.dip_entry_detection\|from backtest.backtest_universe\|from backtest.backtest_config\|open_favorite_team" --include="*.py" .` returns zero matches.
3. `python app.py` boots; old UI URLs are unregistered.
4. After this is complete, **archive this file** to `executed_plans/Backtest_Engine_Redesign_Technical_Plan_step_19.md` and remove the state file at `.claude/execute-plan-state/Backtest_Engine_Redesign_Technical_Plan.json`.

---

## Original Plan Reference

Full original plan with all 19 steps, execution waves, and rationale:
`executed_plans/Backtest_Engine_Redesign_Technical_Plan_steps_1-18.md`

Source product plan (problem statement + migration sequence):
`plans/Backtest_Engine_Redesign_Plan.md` *(stays in `plans/` since Step 19 still references it)*
