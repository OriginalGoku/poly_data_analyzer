"""Out-of-sample + bootstrap validation for the TP×SL bracket strategies.

Reuses the tested first-passage engine in ``nba_tipoff_bracket`` (one game
stream → cached favorite-side paths) and asks the only question that matters
for a "good hypothesis": does the in-sample argmax bracket survive?

- Walk-forward: re-select the argmax bracket on each expanding train slice,
  score it on the next held-out test slice (overfit-honest).
- Bootstrap: resample games at the full-sample argmax bracket → 95% CI and
  P(EV>0) on the per-unit-stake EV.

Works for either ``side`` ("favorite" | "underdog"); the underdog reuses the
favorite path (price = 1 - p), flipping entry and outcome.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import INTERPRETABLE_BAND_LABELS
from nba_tipoff_bracket import _bracket_pnl, _collect_paths, _grid_from_paths

WF_COLUMNS = (
    "band", "side", "n_folds", "mean_test_ev", "std_test_ev",
    "folds_positive", "folds_beat_no_bracket", "mean_stop", "mean_target",
)
BOOT_COLUMNS = (
    "band", "side", "n_games", "argmax_stop", "argmax_target",
    "ev_per_unit_stake", "ev_ci_low", "ev_ci_high", "prob_ev_positive",
    "t_stat", "ev_no_bracket",
)


def _side_view(entry, prices, won, side):
    if side == "favorite":
        return entry, prices, won
    return 1.0 - entry, (1.0 - prices if prices.size else prices), (not won)


def _argmax_bracket_by_band(paths, side, fee, slippage, stop_step, target_step):
    grid = _grid_from_paths(paths, side, fee, slippage, stop_step, target_step)
    if grid.empty:
        return {}
    am = grid[grid["is_argmax"]]
    return {r["band"]: (float(r["stop_price"]), float(r["target_price"])) for _, r in am.iterrows()}


def _band_pnl_at_bracket(paths, side, bracket_by_band, fee, slippage):
    """Per band -> (pnl array at its bracket, pnl array with no bracket)."""
    out: dict[str, list[float]] = {}
    out_no: dict[str, list[float]] = {}
    for band, _date, won, entry, prices in paths:
        if band not in bracket_by_band:
            continue
        stop, target = bracket_by_band[band]
        e, p, w = _side_view(entry, prices, won, side)
        pnl, _ = _bracket_pnl(e, p, w, stop, target, fee, slippage)
        no_pnl, _ = _bracket_pnl(e, p, w, 0.0, 1.0, fee, slippage)  # no SL, no TP
        out.setdefault(band, []).append(pnl)
        out_no.setdefault(band, []).append(no_pnl)
    return out, out_no


def _order(df, key="band"):
    present = [b for b in INTERPRETABLE_BAND_LABELS if b in set(df[key])] if not df.empty else []
    if present:
        df[key] = pd.Categorical(df[key], categories=present, ordered=True)
        df = df.sort_values(key).reset_index(drop=True)
        df[key] = df[key].astype(str)
    return df


def walk_forward_bracket(paths, side, fee, slippage, n_folds=5, stop_step=0.02, target_step=0.02):
    cols = list(WF_COLUMNS)
    if not paths or n_folds < 2:
        return pd.DataFrame(columns=cols)
    ordered = sorted(paths, key=lambda p: p[1])  # by date
    n = len(ordered)
    bounds = [int(round(n * i / n_folds)) for i in range(n_folds + 1)]

    per_band: dict[str, list[tuple]] = {}
    for k in range(1, n_folds):
        train = ordered[: bounds[k]]
        test = ordered[bounds[k] : bounds[k + 1]]
        if not train or not test:
            continue
        brackets = _argmax_bracket_by_band(train, side, fee, slippage, stop_step, target_step)
        if not brackets:
            continue
        pnl_by_band, no_by_band = _band_pnl_at_bracket(test, side, brackets, fee, slippage)
        for band, pnls in pnl_by_band.items():
            stop, target = brackets[band]
            per_band.setdefault(band, []).append(
                (float(np.mean(pnls)), float(np.mean(no_by_band[band])), stop, target)
            )

    rows = []
    for band, folds in per_band.items():
        test_evs = np.array([f[0] for f in folds])
        no_evs = np.array([f[1] for f in folds])
        rows.append({
            "band": band, "side": side, "n_folds": int(len(folds)),
            "mean_test_ev": float(test_evs.mean()),
            "std_test_ev": float(test_evs.std(ddof=1)) if len(test_evs) > 1 else 0.0,
            "folds_positive": int((test_evs > 0).sum()),
            "folds_beat_no_bracket": int((test_evs > no_evs).sum()),
            "mean_stop": float(np.mean([f[2] for f in folds])),
            "mean_target": float(np.mean([f[3] for f in folds])),
        })
    return _order(pd.DataFrame(rows, columns=cols))


def bootstrap_bracket_ci(paths, side, fee, slippage, n_boot=2000, seed=0, stop_step=0.02, target_step=0.02):
    cols = list(BOOT_COLUMNS)
    if not paths:
        return pd.DataFrame(columns=cols)
    brackets = _argmax_bracket_by_band(paths, side, fee, slippage, stop_step, target_step)
    if not brackets:
        return pd.DataFrame(columns=cols)
    pnl_by_band, no_by_band = _band_pnl_at_bracket(paths, side, brackets, fee, slippage)
    rng = np.random.default_rng(seed)

    rows = []
    for band, pnls in pnl_by_band.items():
        arr = np.asarray(pnls)
        n = arr.size
        if n < 2:
            continue
        stop, target = brackets[band]
        idx = rng.integers(0, n, size=(n_boot, n))
        boot_means = arr[idx].mean(axis=1)
        lo, hi = np.percentile(boot_means, [2.5, 97.5])
        std = float(arr.std(ddof=1))
        t = float(arr.mean() / (std / np.sqrt(n))) if std > 0 else 0.0
        rows.append({
            "band": band, "side": side, "n_games": int(n),
            "argmax_stop": stop, "argmax_target": target,
            "ev_per_unit_stake": float(arr.mean()),
            "ev_ci_low": float(lo), "ev_ci_high": float(hi),
            "prob_ev_positive": float(np.mean(boot_means > 0)),
            "t_stat": t, "ev_no_bracket": float(np.mean(no_by_band[band])),
        })
    return _order(pd.DataFrame(rows, columns=cols))


def validate_brackets(
    data_dir, settings, dataset, sides=("favorite", "underdog"),
    n_folds=5, n_boot=2000, seed=0, stop_step=0.02, target_step=0.02,
    base_records_cache_dir=None,
):
    """Collect paths once; return {side: (walk_forward_df, bootstrap_df)}."""
    fee = float(getattr(settings, "stop_loss_fee_bps", 0.0)) / 10000.0
    slippage = float(getattr(settings, "stop_loss_slippage_bps", 0.0)) / 10000.0
    paths = _collect_paths(
        data_dir, settings, dataset,
        "tipoff_interpretable_band", "tipoff_favorite_avg_last_n_pretip_price",
        "tipoff_favorite_won", "tipoff_favorite_team", base_records_cache_dir,
    )
    out = {}
    for side in sides:
        wf = walk_forward_bracket(paths, side, fee, slippage, n_folds, stop_step, target_step)
        boot = bootstrap_bracket_ci(paths, side, fee, slippage, n_boot, seed, stop_step, target_step)
        out[side] = (wf, boot)
    return out
