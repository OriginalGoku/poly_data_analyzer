# NBA Tip-Off Trading Edge — Investigation & Findings (May 2026)

> Status: **one marginal, OOS-survived candidate edge** identified. Everything
> else tested was noise. This document records the approach, the edge, the
> caveats, and every piece of code built to test it.

---

## 1. Executive summary

We set out to find a profitable, deployable trading edge on Polymarket NBA
game markets, entering near tip-off. We tested a sequence of increasingly
rigorous hypotheses (stop-losses, take-profits, TP+SL brackets, a live
win-probability model) on both the **favorite** and **underdog** sides, across
six tip-off price bands, and subjected every promising result to
**out-of-sample (OOS) and bootstrap validation**.

**Result:**

- **Favorite-side exit rules (stop-loss / take-profit / bracket): no edge.**
  All bands' walk-forward EV is negative; all bootstrap CIs span zero.
- **A naive live win-probability model (lead + game-clock): no edge.** The
  market prices score+clock efficiently; the model's disagreements are model
  error, not tradeable mispricing.
- **Underdog side: one survivor.** In **Lean Favorite** games (tip-off favorite
  barely favored, ~0.50–0.53), buying the near-coin-flip other side (~0.49) and
  **taking profit at ~0.71** survived both validation tests:
  - Walk-forward: **+0.042** mean test EV, **positive in 4/4 folds**.
  - Bootstrap: **+0.045** EV, **P(EV>0) = 95.5%**, t = 1.75.

This single candidate is **marginal** (t < 1.96, CI low ≈ −0.007) and exposed to
**multiple-comparisons bias** (one hit out of ~10+ strategies tested). It is a
**hypothesis to confirm on truly held-out future data**, not yet a deployable
edge.

---

## 2. Market mechanics & framing

- Polymarket NBA "team wins" shares trade in **[0, 1]** = implied win
  probability; they settle **$1 if the team wins, $0 if it loses**.
- Per game, the **tip-off favorite** is the team priced > 0.50 at tip-off; the
  **underdog** is the complement (`underdog_price = 1 − favorite_price`).
- Games are bucketed by the favorite's tip-off price into **interpretable
  bands**: Toss-Up, Lean Favorite (0.50–0.53), Lower Moderate (0.53–0.65),
  Upper Moderate (0.65–0.77), Lower Strong (0.77–0.85), Upper Strong (0.85+).
- **Entry price** used throughout: the size-weighted average of the last N=30
  pre-tip favorite-side trades (`tipoff_favorite_avg_last_n_pretip_price`); the
  underdog entry is `1 − that`.
- **Costs:** modelled as `stop_loss_fee_bps = 100` (1¢ per trade) and
  `stop_loss_slippage_bps = 100` (1¢ on market-order stop fills). Take-profits
  are modelled as **limit sells** (fill at target, no slippage); stop-losses as
  **market orders** (slippage applies).
- Dataset: full historical archive, **~2,809 NBA games** after the open-price
  quality filter.

---

## 3. Methodology — the validation discipline

The central lesson of the investigation: **in-sample EV maximization is
misleading**. Picking the best stop/target on the same data you measure it on
produces winner's-curse inflation. The methodology evolved to defeat that:

1. **EV grids with Wilson CIs.** For each band, scan a grid of exit levels;
   compute per-cell EV and Wilson confidence intervals on the stop-out /
   take-profit hit rates. Flag the argmax cell.

2. **Eligibility / grid bounds.** Stops must be **below** entry and targets
   **above** entry — a stop above your own entry triggers instantly under a
   `min_price ≤ stop` model and produces a spurious argmax (this bug pinned the
   first SL grid argmax at 0.98 until fixed).

3. **Full-resolution first-passage (not the 5-min resample).** Scalar in-game
   min/max are *order-blind* — fine for a single barrier, but a **bracket
   (TP + SL) is order-dependent**: it matters whether the take-profit was hit
   *before* the stop. We walk each game's full-resolution favorite-side trade
   path (`cummax`/`cummin` + vectorized `searchsorted`), resolving whichever
   barrier is touched first (ties → take-profit). The 5-min resample
   systematically **overstated** stop-loss EV (Upper Strong: +0.0117 resample
   vs +0.0067 full-resolution) because it missed intra-bar stop touches.

4. **Out-of-sample (OOS) split.** Pick the argmax exit on the earliest 70% of
   games (chronologically), then measure that *fixed* exit on the held-out
   later 30%. `overfit_gap = train_EV − test_EV` quantifies the shrinkage.

5. **Walk-forward.** Generalize the single split into expanding chronological
   folds (5 folds → 4 OOS evaluations); re-select the argmax exit on each train
   slice. A real edge is positive across *most* folds, not one lucky split.

6. **Bootstrap CI + t-stat.** Resample games with replacement (5,000 draws) at
   the full-sample argmax exit; report the 95% CI, `P(EV > 0)`, and the t-stat.
   An edge is credible only if the CI excludes 0 and `P(EV>0)` is near 1.

7. **Multiple-comparisons awareness.** Having tested ~10+ band×side×exit
   combinations, a single p≈0.05 hit is partly expected by chance. Survivors
   are treated as hypotheses requiring fresh-data confirmation.

---

## 4. The investigation, lever by lever

### Lever 0 — Stop-loss on favorites (scalar grid)
Per-band EV-vs-stop grid using the favorite in-game **min** price.
- In-sample: only **Upper Strong** positive (+0.012 at stop 0.16).
- OOS 70/30: the argmax stop was **unstable** (0.16 full-sample vs 0.49 on
  train) — a hallmark of fitting noise.
- Walk-forward + bootstrap: **no band significant**; all CIs span 0, t < 1.
  The stop reliably *reduces* losses (beats no-stop in folds) but never makes a
  band profitable.

### Lever 1 — Take-profit on favorites (scalar grid)
Per-band EV-vs-target grid using the favorite in-game **max** price.
- **Dead.** Every band's optimal target collapses to ~1.0 (= no take-profit).
  Winners almost always pass through high prices (≈100% TP-hit), so a TP just
  caps the frequent winners while salvaging few losers. Net negative.

### Lever 2 — TP × SL bracket (full-resolution first-passage)
The honest version: walk the real path, resolve TP-before-SL.
- Confirmed the resample inflation (see §3.3).
- Favorite side: only Upper Strong mildly positive in-sample; **dead OOS**.

### Lever 3 — Live win-probability model
Empirical `P(favorite wins | game-time bucket, favorite-lead bucket)` fit on a
train slice; measure realized EV of buying when the model says the market
underprices the favorite, on held-out games.
- The model itself is **sane** (win-prob rises cleanly with lead and clock).
- **No tradeable edge.** When the model flagged a large underpricing, the
  *realized* outcome tracked the **market price**, not the model — i.e. the
  market knows more than score+clock. The "mispricings" are model crudeness.

### The pivot to underdogs
Our own data hinted favorites were *overpriced* (fading them had the most
negative-for-favorite EV), implying underdogs were the underpriced side. The
take-profit logic also **flips** for underdogs: most underdogs lose (settle 0),
so a TP that exits on an early in-game spike **salvages the dominant losing
population** — the opposite of favorites.

- In-sample: **4 of 5 underdog bands positive** (vs 1/5 favorites).
- OOS walk-forward + bootstrap: **only Lean Favorite survived** (see §5).
  The promising-looking Lower Strong underdog (+0.024 in-sample) **failed**
  walk-forward (−0.006, positive in 1/4 folds) — in-sample noise.

---

## 5. The edge

> **In Lean Favorite games (tip-off favorite ~0.50–0.53), buy the near-coin-flip
> opposite side (~0.49) at tip-off and place a take-profit limit at ~0.71.
> Exit there if hit; otherwise hold to settlement.**

| Metric | Value |
|---|---|
| Band | Lean Favorite (favorite 0.50–0.53) |
| Side | Underdog (~0.49 entry) |
| Stop-loss | ~0.02 (effectively none) |
| Take-profit target | ~0.71 |
| Walk-forward mean test EV | **+0.042** |
| Walk-forward folds positive | **4 / 4** |
| Bootstrap EV | **+0.045** |
| Bootstrap 95% CI | [−0.007, +0.094] |
| Bootstrap P(EV > 0) | **95.5%** |
| t-stat | 1.75 |
| Take-profit hit rate (in-sample) | ~72% |
| N games | 151 |

**Why it (plausibly) works — volatility harvest on the most uncertain games.**
Lean Favorite games are genuine coin-flips, so prices swing hard in-game. The
~0.49 side spikes above 0.71 at some point in ~72% of these games (lead changes,
runs). The take-profit captures those swings and locks the gain **regardless of
who ultimately wins** — it monetizes in-game volatility rather than betting on
the final outcome. This is precisely why a take-profit pays here but not on
favorites: on favorites, the frequent winners get capped; on coin-flips, the
frequent spikes get harvested.

**This is the only strategy that survived both OOS tests with a positive,
consistent result.**

---

## 6. Caveats (read before risking capital)

1. **Marginal significance.** t = 1.75 < 1.96; the bootstrap CI low (−0.007)
   barely touches zero. Suggestive, not proven.
2. **Multiple-comparisons bias.** ~10+ strategies were searched; one p≈0.05 hit
   is partly expected by chance. **Must be confirmed on truly held-out future
   data** (a date cutoff never touched during this search).
3. **Small sample.** 151 games in the band.
4. **EV is an estimate, not a fill guarantee.** The 1¢ slippage assumption is
   optimistic on thin Polymarket books; the TP relies on a limit fill at 0.71.
5. **Costs matter at this scale.** The edge is ~4.5¢ per unit stake before
   real-world frictions beyond the modelled 1¢.

---

## 7. Code created to test all this

All code lives in the repo root unless noted. Tests are under `tests/`. Full
suite: **388 passing**.

### Configuration
- **`settings.py`** — added three `ChartSettings` fields:
  `tipoff_entry_window_trades` (30), `stop_loss_fee_bps` (100.0),
  `stop_loss_slippage_bps` (100.0). Round-tripped through `to_dict()` and
  `chart_settings.json`. Tests: `tests/test_settings.py`.

### Per-game metrics & caching (`nba_analysis.py`)
- `_in_game_excursion_metrics` — shared min/max/MAE/MFE helper.
- `_compute_in_game_open_favorite_metrics` — extended to compute tip-off-favorite
  in-game path metrics (8 new columns) alongside the open-favorite ones;
  tip-off team/price threaded from the base record (`analytics.py`), **not**
  from `compute_metrics` (a corrected data-provenance assumption).
- `_resolve_score_tipoff_time`, `_compute_tipoff_entry_window_price` — the
  size-weighted last-N pre-tip entry price (`tipoff_favorite_avg_last_n_pretip_price`,
  `tipoff_entry_window_n_used`).
- `build_band_outcome_distribution` — per-band × outcome (win/loss) percentile
  distribution of the tip-off-favorite in-game min price.
- `build_band_stop_loss_ev_grid` — per-band EV-vs-stop grid (scalar min-based),
  Wilson CIs, `is_argmax`; stops capped below entry.
- `build_band_take_profit_ev_grid` — per-band EV-vs-target grid (scalar
  max-based), limit-sell fill; targets above entry plus a 1.0 no-TP reference.
- `build_stop_loss_oos_validation` — chronological 70/30 train/test on the
  stop-loss argmax (`overfit_gap`, `test_beats_no_stop`).
- `_barrier_hit_rate_ci` / `_stopout_rate_ci` — shared above/below crossing-rate
  helpers with Wilson CIs.
- **`nba_tipoff_cache.py`** — `NBA_TIPOFF_CACHE_SCHEMA_VERSION` bumped 1→2;
  `tipoff_entry_window_trades` added to the settings hash.
- Tests: `tests/test_nba_analysis.py`, `tests/test_nba_tipoff_cache.py`.

### Full-resolution bracket engine (`nba_tipoff_bracket.py`)
- `_favorite_ingame_prices` — full-resolution favorite-side in-game price path.
- `_bracket_pnl` — single-game first-passage PnL for a (stop, target) bracket
  (TP limit-sell, SL market-order; ties → TP).
- `_band_grids` — per-band (stop, target) grid bounds.
- `_collect_paths` — **streams each game once**, returns
  `(band, date, favorite_won, favorite_entry, favorite_price_path)`; the
  favorite path is reused for both sides (underdog price = 1 − p).
- `_grid_from_paths(side=…)` — vectorized first-passage EV grid for a side
  (`cummax`/`cummin` + broadcast `searchsorted`); underdog flips price, entry,
  outcome.
- `build_band_bracket_ev_grids` — favorite + underdog grids from **one** stream.
- `build_band_bracket_ev_grid` — single-side convenience wrapper.
- Tests: `tests/test_nba_tipoff_bracket.py` (includes the underdog-TP-salvage
  case and favorite/underdog divergence).

### Live win-probability model (`nba_tipoff_winprob.py`) — Lever 3
- `_time_bucket`, `_lead_bucket`, `_edge_bucket` — bucketers.
- `_favorite_price_series` / `_price_asof` — favorite-side price-at-game-state
  via `datetime64[ns]` asof lookup (fixed a us/ns time-unit asof bug).
- `extract_game_samples` — one sample per score event (time, lead, market
  price, outcome).
- `build_win_prob_table` — empirical `P(win | time, lead)`.
- `evaluate_mispricing` — bucket test samples by model-vs-market edge; realized
  EV of buying the favorite when underpriced.
- `build_winprob_analysis` — streams once, train/test split, returns the table +
  mispricing test. Tests: `tests/test_nba_tipoff_winprob.py`.

### Robustness — scalar stop-loss (`nba_tipoff_robustness.py`)
- `_per_game_stop_pnl` — per-game PnL with **per-row entry** + stop-eligibility
  (a stop above a game's own entry is invalid; this is the genuinely
  entry-sensitive part of the "#3 per-row entry" idea — EV per unit stake is
  otherwise linear in entry, hence unchanged).
- `walk_forward_stop_loss` — expanding folds; re-select stop per train slice.
- `bootstrap_stop_loss_ci` — 95% CI, `P(EV>0)`, t-stat, mean ROI%.
- Tests: `tests/test_nba_tipoff_robustness.py`.

### Bracket validation — both sides (`nba_tipoff_bracket_validation.py`)
*The module that produced the final verdict.*
- `_side_view` — per-game favorite/underdog transform.
- `_argmax_bracket_by_band` — reuses `_grid_from_paths` to pick the argmax
  bracket on any path subset.
- `_band_pnl_at_bracket` — per-game PnL at a fixed bracket (and the no-bracket
  baseline), via `_bracket_pnl`.
- `walk_forward_bracket` — expanding folds; re-select the argmax bracket per
  train slice, score OOS.
- `bootstrap_bracket_ci` — 95% CI, `P(EV>0)`, t-stat at the full-sample argmax
  bracket.
- `validate_brackets` — collects paths **once**, runs walk-forward + bootstrap
  for favorite and underdog. Tests:
  `tests/test_nba_tipoff_bracket_validation.py`.

### Export CLI (`analysis_nba_open_vs_tipoff.py`)
Emits all artifacts and appends matching argmax sections to `summary.md`:
`tipoff_band_min_price_distribution.csv`, `tipoff_band_stop_loss_ev.csv`,
`tipoff_band_take_profit_ev.csv`, `tipoff_stop_loss_oos_validation.csv`,
`tipoff_stop_loss_walk_forward.csv`, `tipoff_stop_loss_bootstrap_ci.csv`, and —
behind the `--path-analysis` flag (heavy full-resolution passes) —
`tipoff_band_bracket_ev.csv`, `tipoff_band_underdog_bracket_ev.csv`,
`winprob_table.csv`, `winprob_mispricing_test.csv`.
- **`scripts/archive_baseline_pre_tipoff_stoploss.sh`** — one-shot baseline CSV
  archival. Tests: `tests/test_analysis_nba_open_tipoff_export.py`.

---

## 8. How to reproduce

```bash
# Fast scalar-only run (SL/TP grids, OOS, walk-forward, bootstrap):
python analysis_nba_open_vs_tipoff.py --data-dir data

# Full run incl. full-resolution bracket (favorite+underdog) + win-prob model
# (re-reads every game's trades once; ~25 min):
python analysis_nba_open_vs_tipoff.py --data-dir data --path-analysis

# The decisive bracket OOS + bootstrap validation (both sides) is in
# nba_tipoff_bracket_validation.validate_brackets(data_dir, settings, dataset).
```

Outputs land in `analysis_outputs/nba_open_tipoff_<timestamp>/`; the `summary.md`
there carries the argmax tables for every analysis above.

---

## 9. Recommended next steps

1. **True forward holdout.** Re-fit the Lean Favorite underdog + TP strategy on
   all data up to a frozen cutoff, then evaluate **only** on games after the
   cutoff that were never touched during this search. This is the cleanest
   defense against the multiple-comparisons caveat.
2. **Richer win-probability model.** Add team strength (Elo/ratings), pace, rest
   (back-to-back), and injuries. Score+clock alone is efficiently priced; a
   better state model is the most plausible route to a *significant* edge.
3. **Sub-population / microstructure.** Segment by liquidity and game state;
   investigate whether thin books create transient mispricings around scoring
   runs (requires order-book/fill data, not just trades).

---

*Investigation conducted May 2026 against the full historical NBA archive.
All analysis code is committed; the full test suite (388 tests) passes.*
