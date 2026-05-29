## Lens status

Functional plan; new analytical columns + EV-grid aggregator + CSV outputs. No UI page in scope.

## Problem Statement

Given the historical NBA dataset and the per-tip-off-band win-rate / drawdown statistics already emitted by `analysis_nba_open_vs_tipoff.py`, determine the EV-maximizing stop-loss price (per long-favorite trade entered near tip-off) for each tip-off interpretable band — separately for Upper Strong and Lower Strong — using the distribution of in-game min price **conditional on eventual tip-off-favorite outcome (win vs loss)**. Three existing-data defects block the answer:

1. In-game min/MAE columns are computed against the **open favorite** team, not the **tip-off favorite** team. When the favorite switches open→tipoff, the recorded drawdown is the wrong team's path.
2. Only mean/median aggregates exist per band; no percentile distributions split by outcome.
3. No multi-trade pre-tip entry-price aggregate (size-weighted avg of last N favorite-side trades) exists — only the single-point `tipoff_favorite_price` is available.

Out of scope: scenario-engine backtest validation (phase 2), Dash page for the new outputs, trailing/multi-level stops.

## Codebase Context

- `nba_analysis.py:916-1010` — `_compute_in_game_open_favorite_metrics` builds open-favorite in-game min/max/MAE/MFE inside the per-game detail loop. Signature: `(trades_df, events, manifest, settings, open_favorite_team, open_favorite_price)`. Branches on `open_favorite_team in (away_team, home_team)`. Tip-off-side parity does not exist yet.
- `nba_analysis.py:855-885` — `_compute_nba_detail_row_from_game` is the streaming entry point that calls `PregameFavoritePathAnalyzer.compute_metrics` (produces `tipoff_favorite_team`, `tipoff_favorite_price` in the `details` dict) then calls the open-favorite in-game metrics function. Tip-off-favorite values are available in `details` before the in-game function runs; they can be threaded in via signature change.
- `nba_analysis.py:385-438` — `build_group_summary` emits per-band aggregations (mean/median of open-favorite in-game min, MAE, etc.). No percentile grid; no outcome split. Pattern uses pandas `groupby().agg(...)` + Wilson CI via `_wilson_interval`.
- `nba_analysis.py:329-383` — `build_summary` returns a frozen `NBAOpenTipoffSummary` dataclass; only mean-shaped scalars. New per-band-per-outcome distribution is a different shape (long-form DataFrame), so it lives next to `build_group_summary`, not inside the summary dataclass.
- `analysis_nba_open_vs_tipoff.py:158-175` — CSV emission point; new CSVs slot in here.
- `chart_settings.json` + `settings.py:11-46` — `ChartSettings` frozen dataclass. `to_dict()` at lines 55-90 enumerates keys explicitly; new fields must be added in three places (dataclass field, `to_dict`, JSON).
- `nba_tipoff_cache.py:12,21-31,50-105` — per-game detail cache. `NBA_TIPOFF_CACHE_SCHEMA_VERSION = 1`. `compute_settings_hash` covers `pregame_min_cum_vol`, `vol_spike_std`, `vol_spike_lookback`, `post_game_buffer_min`, `open_favorite_team`, `open_favorite_price`. Adding new computed columns invalidates payloads; bumping schema version forces recompute. Adding `tipoff_entry_window_trades` to the settings hash makes N changes invalidate cache.
- `analytics.py` `BASE_RECORDS_CACHE_SCHEMA_VERSION = 2` (per CLAUDE.md) — base records live upstream of detail rows; the new columns are computed in the detail layer, so base-records schema is **not** affected.
- `loaders.py:100-102` — `trades_df` schema includes `price`, `size`, `datetime`, `asset`, `team` columns. Sufficient for size-weighted avg of last N favorite-side pre-tip trades.
- `backtest/filters/upper_strong.py` — universe filter exists for one of the two bands. Reused by phase-2 scenario validation (out of scope here).

### Reusable-Code Survey

- `_wilson_interval` (in `nba_analysis.py`) — already used in `build_group_summary` for swing-rate CIs. Reuse for win-stopout / loss-stopout-rate CIs in the EV grid output.
- `groupby().agg(...)` pattern in `build_group_summary` — mirror it for the new aggregator's scaffolding.
- `_safe_mean`, `_nullable_bool_rate`, `_safe_true_count` (in `nba_analysis.py`) — reuse for distribution percentile helpers and outcome rates.
- `PregameFavoritePathAnalyzer.compute_metrics` already returns `tipoff_favorite_team` and `tipoff_favorite_price` in the metrics dict — no new pregame analyzer required; thread these into the in-game function.
- Filesystem search: `utils/`, `lib/`, `src/utils/` — None — searched: `src/utils src/lib src/common src/helpers utils lib common helpers` (none exist; project is flat-layout).
- Repo grounding hints: feature-driven dispatch not used (no `features/<slug>/feature.md`).

## Pre-Change Baseline

Current `analysis_nba_open_vs_tipoff.py` run on the full historical data emits:

- `dataset.csv` — per-game rows with `open_favorite_in_game_min_price`, `open_favorite_max_adverse_excursion`, `tipoff_favorite_won`, `tipoff_interpretable_band`, `favorite_changed_open_to_tipoff`, `tipoff_favorite_price` (single point).
- `tipoff_band_outcome_summary.csv` — per-band mean+median of open-favorite in-game min, win rates, swing rates.
- Quoted user-observed band stats (from page UI): Upper Strong tip-off favorite win rate ≈ 90% with median open-favorite in-game min ≈ 0.80; Lower Strong ≈ 77% with median ≈ 0.63.
- No tip-off-favorite-side in-game min column exists.
- No pre-tip entry-price aggregate column exists.
- No conditional-on-outcome percentile distributions or EV-vs-stop tables exist anywhere in the pipeline or CSVs.

Baseline freeze: pre-change `tipoff_band_outcome_summary.csv` and `dataset.csv` from a full-history run will be archived under `analysis_outputs/baseline_pre_tipoff_stoploss/` before Step 1 begins.

## Verification Signal

- `dataset.csv` post-change includes new columns: `tipoff_favorite_in_game_min_price`, `tipoff_favorite_in_game_max_price`, `tipoff_favorite_max_adverse_excursion`, `tipoff_favorite_max_adverse_excursion_pct`, `tipoff_favorite_max_favorable_excursion`, `tipoff_favorite_max_favorable_excursion_pct`, `tipoff_favorite_avg_last_n_pretip_price`, `tipoff_entry_window_n_used` (actual N when fewer than configured exist).
- On games where `favorite_changed_open_to_tipoff == False`, `tipoff_favorite_in_game_min_price == open_favorite_in_game_min_price` for ≥99% of rows (parity check; floor allows for path-resample edge cases).
- On games where `favorite_changed_open_to_tipoff == True`, the two columns differ in ≥80% of rows (sanity that the new column is doing distinct work).
- New CSV `tipoff_band_min_price_distribution.csv` present with columns: `band`, `outcome` (`win`/`loss`), `n_games`, `p05`, `p10`, `p25`, `p50`, `p75`, `p90`, `p95`.
- New CSV `tipoff_band_stop_loss_ev.csv` present with columns: `band`, `stop_price`, `entry_price_used` (band-level mean or per-row, see Step 4), `n_games`, `win_stopout_rate`, `win_stopout_ci_low`, `win_stopout_ci_high`, `loss_stopout_rate`, `loss_stopout_ci_low`, `loss_stopout_ci_high`, `ev_per_unit_stake`, `ev_no_stop_reference`.
- Per-band rows include `stop_price = 0.0` (no-stop reference) and an `is_argmax` flag set on the EV-maximizing row.
- Unit tests for the new tip-off in-game metrics function on a synthetic two-team trades_df where favorite switches open→tipoff — assert tip-off columns track the tip-off-side path, open columns track the open-side path.
- Unit test for EV grid on a hand-rolled mini-distribution where the closed-form answer is known.
- Smoke run: `python analysis_nba_open_vs_tipoff.py --data-dir data --start-date 2024-01-01 --end-date 2024-01-31` completes; new CSVs nonempty.

## Implementation Steps

### Step 1: Settings additions
Files: settings.py, chart_settings.json
Depends on: none

**What changes:**
- Add `tipoff_entry_window_trades: int = 30` field to `ChartSettings`.
- Add `stop_loss_fee_bps: float = 0.0` and `stop_loss_slippage_bps: float = 0.0` defaults (real values to be tuned later; defaults make initial run match a frictionless EV baseline).
- Add matching keys to `to_dict()` enumeration and to `chart_settings.json`.

**Test strategy:**
- Existing `ChartSettings.from_dict` / `to_dict` round-trip is covered by the JSON load; add a tiny test asserting the three new keys round-trip with defaults.

### Step 2: Tip-off-favorite in-game path metrics
Files: nba_analysis.py
Depends on: none

**What changes:**
- Refactor `_compute_in_game_open_favorite_metrics` signature to also accept `tipoff_favorite_team: str | None` and `tipoff_favorite_price: float | None`.
- After the existing open-favorite branch, add a parallel branch that computes `tipoff_favorite_in_game_min_price`, `tipoff_favorite_in_game_max_price`, `tipoff_favorite_time_to_min_seconds`, `tipoff_favorite_time_to_max_seconds`, `tipoff_favorite_max_adverse_excursion`, `tipoff_favorite_max_adverse_excursion_pct`, `tipoff_favorite_max_favorable_excursion`, `tipoff_favorite_max_favorable_excursion_pct`.
- Initialise all eight new keys to `None` in the empty-metrics dict.
- Branch skipped (values stay `None`) when `tipoff_favorite_team` is not one of `away_team` / `home_team` or when its price is `None`.

**Test strategy:**
- Unit test: synthetic trades_df with known min/max for both team sides + a constructed manifest; assert tip-off columns track tip-off team and open columns track open team independently.
- Parity test: when `open_favorite_team == tipoff_favorite_team`, the two min-price columns are equal.

### Step 3: Tip-off-favorite pre-tip windowed entry price
Files: nba_analysis.py
Depends on: Step 1, Step 2

**What changes:**
- New helper `_compute_tipoff_entry_window_price(trades_df, manifest, tipoff_favorite_team, tipoff_time, n_trades) -> tuple[float | None, int]` returning size-weighted avg price (on the tip-off favorite side) of the last N pre-tip trades plus actual count used.
- Definition of "favorite-side trades": filter `trades_df` to rows before `tipoff_time`, transform `price` to favorite-team-perspective probability (mirror the existing `away_price`/`home_price` logic in the in-game function), then take the last N rows by `datetime` and compute `sum(price * size) / sum(size)`.
- Wire it into `_compute_nba_detail_row_from_game` after `PregameFavoritePathAnalyzer.compute_metrics` returns (since `tipoff_favorite_team` lives in `details`).
- Add two output keys: `tipoff_favorite_avg_last_n_pretip_price`, `tipoff_entry_window_n_used`. Both `None` if N=0 or tip-off favorite is undetermined.

**Test strategy:**
- Unit test: synthetic trades with known size-weighted last-N avg on each side; assert correct selection by tip-off favorite, correct size-weighting, correct N truncation when fewer than N trades exist.

### Step 4: Per-game cache schema bump + settings-hash extension
Files: nba_tipoff_cache.py
Depends on: Step 1, Step 2, Step 3

**What changes:**
- Bump `NBA_TIPOFF_CACHE_SCHEMA_VERSION` from 1 to 2 (new columns in payload).
- Add `int(getattr(settings, "tipoff_entry_window_trades", 0))` to `compute_settings_hash`'s tuple so changing N invalidates cache.
- No payload-shape change beyond additive columns from Steps 2-3.

**Test strategy:**
- Unit test: write a v1 payload, attempt load, assert miss → recompute path.
- Unit test: two different `tipoff_entry_window_trades` values produce different settings hashes.

### Step 5: Conditional percentile-distribution aggregator
Files: nba_analysis.py
Depends on: Step 2, Step 4

**What changes:**
- New method on `NBAOpenTipoffAnalysisService`: `build_band_outcome_distribution(dataset, band_col="tipoff_interpretable_band", value_col="tipoff_favorite_in_game_min_price") -> pd.DataFrame`.
- Group by `(band_col, tipoff_favorite_won)`; for each group compute `n_games`, percentiles `p05, p10, p25, p50, p75, p90, p95` via `np.nanpercentile`. Long-form output: one row per `(band, outcome)`.
- Skip groups with `tipoff_favorite_won` null (games with no outcome).
- Honor `GROUP_ORDERINGS[band_col]` ordering when present.

**Test strategy:**
- Unit test on a synthetic dataset with two bands × two outcomes and known percentile values.
- Empty-dataset edge case returns empty DataFrame.

### Step 6: Stop-loss EV grid optimizer
Files: nba_analysis.py
Depends on: Step 3, Step 5

**What changes:**
- New method: `build_band_stop_loss_ev_grid(dataset, settings, band_col="tipoff_interpretable_band", entry_col="tipoff_favorite_avg_last_n_pretip_price", min_price_col="tipoff_favorite_in_game_min_price", outcome_col="tipoff_favorite_won", stop_grid: tuple[float, ...] | None = None) -> pd.DataFrame`.
- Default grid: `np.arange(0.0, 0.99, 0.01)` (configurable via argument; tight enough for actionable resolution, no settings key required).
- Per band:
  - Compute band-level reference entry `E = mean(entry_col)` over rows with both `entry_col` and `outcome_col` non-null. Single E per band keeps the table interpretable; per-row EV variant can be a follow-up.
  - For each candidate stop `P` in grid:
    - Among eventual winners (`outcome_col == True`): `win_stopout_rate = P(min_price_col <= P | win)`.
    - Among eventual losers: `loss_stopout_rate = P(min_price_col <= P | loss)`.
    - Wilson CIs on both using `_wilson_interval`.
    - Apply fee + slippage from settings: `stop_fill = P - (slippage_bps / 10000)`, `payoff_haircut_per_trade = fee_bps / 10000` applied to every leg.
    - EV per unit stake:
      `EV(P) = WinRate * [ (1 - win_stopout_rate) * (1.0 - E) + win_stopout_rate * (stop_fill - E) ] + LossRate * [ (1 - loss_stopout_rate) * (0.0 - E) + loss_stopout_rate * (stop_fill - E) ] - payoff_haircut_per_trade`
      where `WinRate = mean(outcome_col)` within the band.
    - Special-case `P = 0`: no-stop; `ev_no_stop_reference = WinRate * (1 - E) + LossRate * (-E) - payoff_haircut_per_trade`.
  - Mark `is_argmax = True` on the row with the highest EV per band.
- Output: long-form DataFrame with all rows for all bands; `entry_price_used` populated per band; `ev_no_stop_reference` is the same value across every row in a band.

**Test strategy:**
- Unit test on hand-rolled mini-distribution where closed-form argmax is known (e.g., 100% win rate → optimum is P=0; 0% win rate → optimum is P close to entry).
- Edge case: band with zero outcome data returns no rows (or an empty `n_games=0` row that is filtered out — pick one and test).
- Fee/slippage = 0 reproduces the frictionless EV closed form.

### Step 7: CSV emission + baseline archival
Files: analysis_nba_open_vs_tipoff.py
Depends on: Step 5, Step 6

**What changes:**
- After existing CSV emissions (`analysis_nba_open_vs_tipoff.py:175`), call the two new aggregators and write `tipoff_band_min_price_distribution.csv` and `tipoff_band_stop_loss_ev.csv` to `run_dir`.
- Append a "Stop-Loss EV (per tip-off band)" section to `summary.md` with the argmax row per band: `band`, `argmax stop_price`, `EV`, `EV no-stop`, `win_stopout_rate`, `loss_stopout_rate`, `n_games`.
- One-shot script `scripts/archive_baseline_pre_tipoff_stoploss.sh` (or inline in the run instructions) that copies current `dataset.csv` + `tipoff_band_outcome_summary.csv` from a baseline run into `analysis_outputs/baseline_pre_tipoff_stoploss/` before deploying the code changes. (Manual step, documented in the PR; not automated in the analysis CLI.)

**Test strategy:**
- Smoke test: run the analysis CLI against a 30-day slice; assert both new CSVs exist with the expected column headers and the EV CSV contains an `is_argmax == True` row per band.

### Step 8: Documentation
Files: CLAUDE.md
Depends on: Step 4, Step 7

**What changes:**
- Note new columns under "Dashboard & Analytics" → `nba_analysis.py` description (or wherever `nba_analysis` is described; if absent, append a brief entry).
- Bump-of-record for `NBA_TIPOFF_CACHE_SCHEMA_VERSION = 2` in the cache convention bullet (currently the bullet enumerates which sidecars carry which fields).
- New settings keys: `tipoff_entry_window_trades`, `stop_loss_fee_bps`, `stop_loss_slippage_bps`.

**Test strategy:**
- Manual diff review against actual code state.

## Execution Preview

- Wave 0 (parallel): Step 1, Step 2
- Wave 1: Step 3 (depends on 1, 2)
- Wave 2: Step 4 (depends on 1, 2, 3)
- Wave 3 (parallel): Step 5 (depends on 2, 4), Step 6 (depends on 3, 5 — falls to Wave 4)

Recomputed dependencies:
- Wave 0: Step 1, Step 2
- Wave 1: Step 3
- Wave 2: Step 4
- Wave 3: Step 5
- Wave 4: Step 6
- Wave 5: Step 7
- Wave 6: Step 8

Total waves: 7. Max parallelism: 2 (Wave 0). Critical path: 1 → 3 → 4 → 5 → 6 → 7 → 8 (7 steps).

## Risk Flags

- **Path-resample granularity** — In-game min comes from a 5-minute resample (`PATH_RESAMPLE_FREQ = "5min"`); a stop touched between bars may be missed. Acceptable for analytical EV bound; flag in code comment and in `summary.md`.
- **Stop-fill assumption** — `stop_fill = P - slippage_bps/10000` is a constant haircut. Real fills on thin Polymarket books can be worse. Defaults to 0 in Step 1; tune before claiming positive EV.
- **Outcome label coverage** — Games where `tipoff_favorite_won` is null (no final winner derivable) are silently excluded from EV. Sample loss should be reported in `summary.md`.
- **Sample size per band** — Upper Strong + Lower Strong cell counts are unknown without a run. Wilson CIs on win/loss stopout rates surface noise; if a band's `n_games < ~50`, treat argmax as advisory, not actionable.
- **No graphify present** — `graphify-out/GRAPH_REPORT.md` absent; reuse-survey is filesystem-only. Acceptable for a flat-layout project.
- **Project rules absent** — `project-rules.md` not present; section omitted per skill contract.
- **Settings hash backward incompatibility** — Existing `cache/<date>/<match_id>_nba_tipoff.json` payloads will be invalidated by the schema bump in Step 4. A full reanalysis run rebuilds them; cost is on the order of the original detail-loop wall-time. Document in the PR.

## Open Questions

- **Per-row EV vs band-level entry mean** — Step 6 uses a single band-level `E = mean(entry_col)`. A per-row EV (use each game's own entry, then aggregate EV across rows) is more faithful but harder to read. Stay with band-level for v1; revisit if argmax curves look unstable.
- **Stop-grid resolution** — 1¢ grid (`0.00..0.99`) is chosen for resolution. If results are noisy, coarsen to 2¢ or restrict to `[0.30, entry]`.
- **N sweep** — Single N (30) committed. If the entry-price avg is volatile, a follow-up should sweep N ∈ {10, 20, 30, 50, 100} as a sensitivity check; not in scope for this plan.

## Verification

- `pytest tests/` passes including new tests in Steps 2, 3, 4, 5, 6.
- Full-history run of `python analysis_nba_open_vs_tipoff.py --data-dir data` produces non-empty new CSVs.
- `tipoff_band_outcome_summary.csv` (pre-existing) values are unchanged vs the baseline archive (the new code adds columns/CSVs; existing aggregations must not shift).
- `summary.md` argmax-stop rows reviewed manually; sanity check that Lower Strong argmax is at or near 0 (per probe expectation) and Upper Strong argmax sits between entry and the loser percentile midpoint.
- `git diff -- chart_settings.json` shows exactly three additive keys.

<!-- toolkit: check=clean waves=clean gate=fired:open-questions -->
