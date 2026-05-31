"""Robustness checks for the tip-off stop-loss hypothesis.

Three dataset-only analyses (no game re-stream):

1. Walk-forward — expanding chronological folds; pick the argmax stop on each
   train slice, score it on the next test slice. Guards against the single-split
   luck of the 70/30 OOS check.
2. Bootstrap CI — resample games (with replacement) to put a confidence band and
   a one-sided p-value on each band's EV at its full-sample argmax stop.
3. Per-row entry — uses each game's own entry price with stop-eligibility
   (a stop above a game's own entry is invalid and treated as no-stop). EV per
   unit stake is linear in entry, so this differs from the band-mean EV only via
   eligibility; the ROI% column is the genuinely entry-sensitive view.

Per-game PnL (per unit stake), stop ``P`` with per-row entry ``E_i``:
  - eligible (P < E_i) and min_price_i <= P -> stopped at ``P - slippage``
  - otherwise -> settle at 1 (win) or 0 (loss)
  minus a flat per-trade ``fee``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import INTERPRETABLE_BAND_LABELS

WALK_FORWARD_COLUMNS = (
    "band",
    "n_folds",
    "mean_test_ev",
    "std_test_ev",
    "folds_positive",
    "folds_beat_no_stop",
    "mean_train_stop",
)

BOOTSTRAP_COLUMNS = (
    "band",
    "n_games",
    "argmax_stop",
    "ev_per_unit_stake",
    "ev_ci_low",
    "ev_ci_high",
    "prob_ev_positive",
    "t_stat",
    "mean_roi_pct",
    "ev_no_stop",
)


def _fee_slippage(settings) -> tuple[float, float]:
    fee = float(getattr(settings, "stop_loss_fee_bps", 0.0)) / 10000.0
    slippage = float(getattr(settings, "stop_loss_slippage_bps", 0.0)) / 10000.0
    return fee, slippage


def _per_game_stop_pnl(
    min_prices: np.ndarray,
    wons: np.ndarray,
    entries: np.ndarray,
    stop: float,
    fee: float,
    slippage: float,
) -> np.ndarray:
    """Vectorized per-game PnL per unit stake under stop ``stop`` (per-row entry).

    A stop is only applied where it is *below* that game's own entry
    (eligibility); otherwise the game settles.
    """
    eligible = stop < entries
    stopped = eligible & (min_prices <= stop)
    settle = np.where(wons, 1.0, 0.0) - entries
    stop_pnl = (stop - slippage) - entries
    return np.where(stopped, stop_pnl, settle) - fee


def _stop_grid(entry_ref: float, step: float = 0.01) -> np.ndarray:
    grid = np.arange(0.0, max(entry_ref, step), step)
    return np.round(grid, 4)


def _argmax_stop(
    min_prices: np.ndarray,
    wons: np.ndarray,
    entries: np.ndarray,
    grid: np.ndarray,
    fee: float,
    slippage: float,
) -> tuple[float, float]:
    """Return (argmax_stop, ev_at_argmax) scanning ``grid`` (EV = mean per-game PnL)."""
    best_stop, best_ev = 0.0, -np.inf
    for stop in grid:
        ev = float(np.mean(_per_game_stop_pnl(min_prices, wons, entries, stop, fee, slippage)))
        if ev > best_ev:
            best_ev, best_stop = ev, float(stop)
    return best_stop, best_ev


def _band_arrays(group: pd.DataFrame, min_col: str, outcome_col: str, entry_col: str):
    sub = group[group[outcome_col].notna() & group[entry_col].notna()]
    if sub.empty:
        return None
    min_prices = pd.to_numeric(sub[min_col], errors="coerce").to_numpy(dtype=float)
    wons = sub[outcome_col].astype(bool).to_numpy()
    entries = pd.to_numeric(sub[entry_col], errors="coerce").to_numpy(dtype=float)
    ok = ~np.isnan(min_prices) & ~np.isnan(entries)
    if not ok.any():
        return None
    return min_prices[ok], wons[ok], entries[ok]


def _order(result: pd.DataFrame) -> pd.DataFrame:
    present = [b for b in INTERPRETABLE_BAND_LABELS if b in set(result["band"])] if not result.empty else []
    if present:
        result["band"] = pd.Categorical(result["band"], categories=present, ordered=True)
        result = result.sort_values("band").reset_index(drop=True)
        result["band"] = result["band"].astype(str)
    return result


def walk_forward_stop_loss(
    dataset: pd.DataFrame,
    settings,
    n_folds: int = 5,
    band_col: str = "tipoff_interpretable_band",
    entry_col: str = "tipoff_favorite_avg_last_n_pretip_price",
    min_col: str = "tipoff_favorite_in_game_min_price",
    outcome_col: str = "tipoff_favorite_won",
) -> pd.DataFrame:
    """Expanding-window walk-forward: argmax stop on train, score on next test slice."""
    cols = list(WALK_FORWARD_COLUMNS)
    required = {band_col, entry_col, min_col, outcome_col, "date"}
    if dataset.empty or not required.issubset(dataset.columns) or n_folds < 2:
        return pd.DataFrame(columns=cols)

    fee, slippage = _fee_slippage(settings)
    ordered = dataset.sort_values("date").reset_index(drop=True)
    n = len(ordered)
    # Fold boundaries: train grows, test = next block. K folds -> K-1 evaluations.
    bounds = [int(round(n * i / n_folds)) for i in range(n_folds + 1)]

    per_band: dict[str, list[tuple[float, float, float]]] = {}
    for k in range(1, n_folds):
        train = ordered.iloc[: bounds[k]]
        test = ordered.iloc[bounds[k] : bounds[k + 1]]
        if train.empty or test.empty:
            continue
        for band, train_grp in train.groupby(band_col):
            tr = _band_arrays(train_grp, min_col, outcome_col, entry_col)
            te_grp = test[test[band_col] == band]
            te = _band_arrays(te_grp, min_col, outcome_col, entry_col)
            if tr is None or te is None:
                continue
            grid = _stop_grid(float(np.mean(tr[2])))
            stop, _ = _argmax_stop(*tr, grid, fee, slippage)
            test_ev = float(np.mean(_per_game_stop_pnl(*te, stop, fee, slippage)))
            test_no_stop = float(np.mean(_per_game_stop_pnl(*te, 0.0, fee, slippage)))
            per_band.setdefault(band, []).append((stop, test_ev, test_no_stop))

    rows = []
    for band, fold_results in per_band.items():
        stops = np.array([f[0] for f in fold_results])
        test_evs = np.array([f[1] for f in fold_results])
        no_stops = np.array([f[2] for f in fold_results])
        rows.append(
            {
                "band": band,
                "n_folds": int(len(fold_results)),
                "mean_test_ev": float(test_evs.mean()),
                "std_test_ev": float(test_evs.std(ddof=1)) if len(test_evs) > 1 else 0.0,
                "folds_positive": int((test_evs > 0).sum()),
                "folds_beat_no_stop": int((test_evs > no_stops).sum()),
                "mean_train_stop": float(stops.mean()),
            }
        )
    return _order(pd.DataFrame(rows, columns=cols))


def bootstrap_stop_loss_ci(
    dataset: pd.DataFrame,
    settings,
    n_boot: int = 2000,
    seed: int = 0,
    band_col: str = "tipoff_interpretable_band",
    entry_col: str = "tipoff_favorite_avg_last_n_pretip_price",
    min_col: str = "tipoff_favorite_in_game_min_price",
    outcome_col: str = "tipoff_favorite_won",
) -> pd.DataFrame:
    """Bootstrap 95% CI + one-sided p(EV>0) per band at its full-sample argmax stop.

    Uses per-row entries with stop-eligibility (#3). Reports mean ROI% as the
    entry-sensitive view alongside the per-unit-stake EV.
    """
    cols = list(BOOTSTRAP_COLUMNS)
    required = {band_col, entry_col, min_col, outcome_col}
    if dataset.empty or not required.issubset(dataset.columns):
        return pd.DataFrame(columns=cols)

    fee, slippage = _fee_slippage(settings)
    rng = np.random.default_rng(seed)

    rows = []
    for band, grp in dataset.groupby(band_col):
        arrs = _band_arrays(grp, min_col, outcome_col, entry_col)
        if arrs is None:
            continue
        min_prices, wons, entries = arrs
        n = len(min_prices)
        if n < 2:
            continue
        grid = _stop_grid(float(np.mean(entries)))
        stop, ev = _argmax_stop(min_prices, wons, entries, grid, fee, slippage)

        pnl = _per_game_stop_pnl(min_prices, wons, entries, stop, fee, slippage)
        no_stop_pnl = _per_game_stop_pnl(min_prices, wons, entries, 0.0, fee, slippage)
        roi = pnl / entries  # entry-sensitive (#3)

        idx = rng.integers(0, n, size=(n_boot, n))
        boot_means = pnl[idx].mean(axis=1)
        ci_low, ci_high = np.percentile(boot_means, [2.5, 97.5])
        std = float(pnl.std(ddof=1))
        t_stat = float(np.mean(pnl) / (std / np.sqrt(n))) if std > 0 else 0.0

        rows.append(
            {
                "band": band,
                "n_games": int(n),
                "argmax_stop": float(stop),
                "ev_per_unit_stake": float(np.mean(pnl)),
                "ev_ci_low": float(ci_low),
                "ev_ci_high": float(ci_high),
                "prob_ev_positive": float(np.mean(boot_means > 0)),
                "t_stat": t_stat,
                "mean_roi_pct": float(np.mean(roi) * 100.0),
                "ev_no_stop": float(np.mean(no_stop_pnl)),
            }
        )
    return _order(pd.DataFrame(rows, columns=cols))
