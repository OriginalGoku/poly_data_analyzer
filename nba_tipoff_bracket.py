"""Per-band take-profit × stop-loss bracket EV grid for NBA tip-off entries.

Unlike the single-barrier scalar grids in ``nba_analysis`` (which use only the
in-game min/max), a bracket outcome is **order-dependent**: it matters whether
the take-profit was reached *before* the stop-loss. This module therefore walks
each game's full-resolution favorite-side price path and resolves first-passage
(whichever barrier is touched first wins; ties resolve to the take-profit, like
``backtest.exits.tp_sl``).

Performance: each game's trades are read once via ``stream_game_analytics``; the
entire TP×SL grid for a band is evaluated in memory with ``cummax``/``cummin`` +
vectorized ``searchsorted`` — no per-cell game reload.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from analytics import INTERPRETABLE_BAND_LABELS, stream_game_analytics

BRACKET_GRID_COLUMNS = (
    "band",
    "stop_price",
    "target_price",
    "entry_price_used",
    "n_games",
    "tp_exit_rate",
    "sl_exit_rate",
    "settle_rate",
    "ev_per_unit_stake",
    "ev_no_bracket_reference",
    "is_argmax",
)


def _favorite_ingame_prices(
    trades_df: pd.DataFrame,
    events: list[dict] | None,
    manifest: dict,
    settings,
    fav_team: str | None,
) -> np.ndarray:
    """Full-resolution favorite-side in-game price path, time-ordered.

    Window + favorite-side transform mirror
    ``nba_analysis._compute_in_game_open_favorite_metrics`` so the bracket aligns
    with the scalar min/max columns, but without the 5-minute resample.
    """
    if not events or fav_team is None:
        return np.array([], dtype=float)
    if len(manifest.get("token_ids", [])) < 2 or len(manifest.get("outcomes", [])) < 2:
        return np.array([], dtype=float)

    score_events = [
        e
        for e in events
        if e.get("time_actual_dt") is not None
        and e.get("away_score") is not None
        and e.get("home_score") is not None
    ]
    if not score_events:
        return np.array([], dtype=float)

    tipoff_time = min(e["time_actual_dt"] for e in score_events)
    game_end = max(e["time_actual_dt"] for e in score_events) + pd.Timedelta(
        minutes=float(getattr(settings, "post_game_buffer_min", 10))
    )
    ingame = trades_df[
        (trades_df["datetime"] >= tipoff_time) & (trades_df["datetime"] <= game_end)
    ].sort_values("datetime")
    if ingame.empty:
        return np.array([], dtype=float)

    away_token = manifest["token_ids"][0]
    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]
    if fav_team not in (away_team, home_team):
        return np.array([], dtype=float)

    away_price = ingame["price"].astype(float).to_numpy().copy()
    home_mask = (ingame["asset"] != away_token).to_numpy()
    away_price[home_mask] = 1.0 - away_price[home_mask]
    fav_price = away_price if fav_team == away_team else 1.0 - away_price
    return fav_price


def _bracket_pnl(
    entry: float,
    prices: np.ndarray,
    won: bool,
    stop: float | None,
    target: float | None,
    fee: float,
    slippage: float,
) -> tuple[float, str]:
    """First-passage PnL per unit stake for one game under a (stop, target) bracket.

    Returns ``(pnl, exit_kind)`` where exit_kind is ``take_profit`` /
    ``stop_loss`` / ``settle``. TP is a limit sell (fills at target, no
    slippage); SL is a market order (fills at ``stop - slippage``).
    """
    settle_payoff = (1.0 if won else 0.0) - entry - fee
    n = prices.size
    if n == 0:
        return settle_payoff, "settle"

    cummax = np.maximum.accumulate(prices)
    cummin = np.minimum.accumulate(prices)
    # First index where running max >= target (cummax is non-decreasing).
    i_tp = int(np.searchsorted(cummax, target, side="left")) if target is not None else n
    # First index where running min <= stop (cummin is non-increasing -> negate).
    i_sl = int(np.searchsorted(-cummin, -stop, side="left")) if stop is not None else n

    tp_hit = i_tp < n
    sl_hit = i_sl < n
    if tp_hit and (not sl_hit or i_tp <= i_sl):  # ties -> take-profit
        return (target - entry - fee), "take_profit"
    if sl_hit:
        return ((stop - slippage) - entry - fee), "stop_loss"
    return settle_payoff, "settle"


def _band_grids(entry: float, stop_step: float, target_step: float):
    """(stop_grid, target_grid) for a band: stops below entry, targets above."""
    stop_grid = [round(float(x), 4) for x in np.arange(0.0, entry, stop_step)]
    if not stop_grid or stop_grid[0] != 0.0:
        stop_grid = [0.0, *stop_grid]
    target_grid = [round(float(x), 4) for x in np.arange(entry + target_step, 1.0, target_step)]
    target_grid.append(1.0)  # 1.0 == no take-profit (never triggered)
    return stop_grid, target_grid


def _collect_paths(
    data_dir,
    settings,
    dataset: pd.DataFrame,
    band_col: str,
    entry_col: str,
    outcome_col: str,
    fav_team_col: str,
    base_records_cache_dir,
) -> list[tuple[str, str, bool, float, np.ndarray]]:
    """Stream games once -> list of (band, date, favorite_won, favorite_entry, fav_price_path).

    The favorite-side path is reused for both sides (underdog path = 1 - path).
    """
    valid = dataset[
        (dataset["sport"] == "nba")
        & dataset[outcome_col].notna()
        & dataset[entry_col].notna()
        & dataset[band_col].notna()
        & dataset[fav_team_col].notna()
    ]
    if valid.empty:
        return []
    lookup = {
        (r["date"], r["match_id"]): (
            r[band_col],
            bool(r[outcome_col]),
            float(r[entry_col]),
            r[fav_team_col],
        )
        for _, r in valid.iterrows()
    }

    paths = []
    for base_record, get_game in stream_game_analytics(
        data_dir=data_dir,
        pregame_min_cum_vol=float(getattr(settings, "pregame_min_cum_vol", 0)),
        base_records_cache_dir=str(base_records_cache_dir) if base_records_cache_dir else None,
    ):
        key = (base_record.get("date"), base_record.get("match_id"))
        if key not in lookup:
            continue
        band, won, entry, fav_team = lookup[key]
        game = get_game()
        prices = _favorite_ingame_prices(
            game["trades_df"], game["events"], game["manifest"], settings, fav_team
        )
        paths.append((band, key[0], won, entry, prices))
    return paths


def _grid_from_paths(
    paths: list[tuple[str, bool, float, np.ndarray]],
    side: str,
    fee: float,
    slippage: float,
    stop_step: float,
    target_step: float,
) -> pd.DataFrame:
    """Aggregate the per-band TP×SL grid for one side from cached favorite paths.

    ``side='underdog'`` flips price (1-p), entry (1-E) and outcome (not won); the
    first-passage logic is otherwise identical.
    """
    cols = list(BRACKET_GRID_COLUMNS)
    if not paths:
        return pd.DataFrame(columns=cols)

    def _side_entry(entry: float) -> float:
        return entry if side == "favorite" else 1.0 - entry

    # Pass 1: band-level mean entry on the traded side.
    band_entries: dict[str, list[float]] = {}
    for band, _date, _won, entry, _prices in paths:
        band_entries.setdefault(band, []).append(_side_entry(entry))
    band_E, band_stops, band_targets = {}, {}, {}
    acc_pnl, acc_tp, acc_sl, acc_n, band_win = {}, {}, {}, {}, {}
    for band, entries in band_entries.items():
        E = float(np.mean(entries))
        if np.isnan(E) or E <= 0.0 or E >= 1.0:
            continue
        stops, targets = _band_grids(E, stop_step, target_step)
        band_E[band] = E
        band_stops[band] = stops
        band_targets[band] = targets
        acc_pnl[band] = np.zeros((len(stops), len(targets)))
        acc_tp[band] = np.zeros((len(stops), len(targets)))
        acc_sl[band] = np.zeros((len(stops), len(targets)))
        acc_n[band] = 0
        band_win[band] = []

    if not band_E:
        return pd.DataFrame(columns=cols)

    # Pass 2: accumulate first-passage PnL across the grid.
    for band, _date, fav_won, entry, fav_prices in paths:
        if band not in band_E:
            continue
        E = band_E[band]
        stops = band_stops[band]
        targets = band_targets[band]
        won = fav_won if side == "favorite" else (not fav_won)
        prices = fav_prices if side == "favorite" else (1.0 - fav_prices)

        if prices.size == 0:
            acc_pnl[band] += (1.0 if won else 0.0) - E - fee
            acc_n[band] += 1
            band_win[band].append(won)
            continue

        cummax = np.maximum.accumulate(prices)
        cummin = np.minimum.accumulate(prices)
        n = prices.size
        i_tp = np.searchsorted(cummax, np.asarray(targets), side="left")
        i_sl = np.searchsorted(-cummin, -np.asarray(stops), side="left")
        tp_hit = i_tp < n
        sl_hit = i_sl < n
        tp_first = tp_hit[None, :] & (~sl_hit[:, None] | (i_tp[None, :] <= i_sl[:, None]))
        sl_first = sl_hit[:, None] & ~tp_first
        settle_mask = ~tp_first & ~sl_first

        tp_pnl = np.asarray(targets)[None, :] - E - fee
        sl_pnl = (np.asarray(stops)[:, None] - slippage) - E - fee
        settle_pnl = (1.0 if won else 0.0) - E - fee
        pnl = np.where(tp_first, tp_pnl, 0.0)
        pnl = np.where(sl_first, sl_pnl, pnl)
        pnl = np.where(settle_mask, settle_pnl, pnl)

        acc_pnl[band] += pnl
        acc_tp[band] += tp_first
        acc_sl[band] += sl_first
        acc_n[band] += 1
        band_win[band].append(won)

    rows = []
    for band in band_E:
        n_games = acc_n[band]
        if n_games == 0:
            continue
        E = band_E[band]
        stops, targets = band_stops[band], band_targets[band]
        ev = acc_pnl[band] / n_games
        tp_rate = acc_tp[band] / n_games
        sl_rate = acc_sl[band] / n_games
        settle_rate = 1.0 - tp_rate - sl_rate
        win_rate = float(np.mean(band_win[band]))
        ev_no_bracket = win_rate * (1.0 - E) + (1.0 - win_rate) * (-E) - fee
        best = np.unravel_index(int(np.argmax(ev)), ev.shape)
        for si, stop in enumerate(stops):
            for ti, target in enumerate(targets):
                rows.append(
                    {
                        "band": band,
                        "stop_price": float(stop),
                        "target_price": float(target),
                        "entry_price_used": E,
                        "n_games": n_games,
                        "tp_exit_rate": float(tp_rate[si, ti]),
                        "sl_exit_rate": float(sl_rate[si, ti]),
                        "settle_rate": float(settle_rate[si, ti]),
                        "ev_per_unit_stake": float(ev[si, ti]),
                        "ev_no_bracket_reference": ev_no_bracket,
                        "is_argmax": (si, ti) == best,
                    }
                )

    result = pd.DataFrame(rows, columns=cols)
    present = [b for b in INTERPRETABLE_BAND_LABELS if b in set(result["band"])] if not result.empty else []
    if present:
        result["band"] = pd.Categorical(result["band"], categories=present, ordered=True)
        result = result.sort_values(["band", "stop_price", "target_price"]).reset_index(drop=True)
        result["band"] = result["band"].astype(str)
    return result


def build_band_bracket_ev_grids(
    data_dir: str,
    settings,
    dataset: pd.DataFrame,
    sides: tuple[str, ...] = ("favorite", "underdog"),
    band_col: str = "tipoff_interpretable_band",
    entry_col: str = "tipoff_favorite_avg_last_n_pretip_price",
    outcome_col: str = "tipoff_favorite_won",
    fav_team_col: str = "tipoff_favorite_team",
    stop_step: float = 0.02,
    target_step: float = 0.02,
    base_records_cache_dir: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Per-band TP×SL bracket grids for multiple sides from a single game stream.

    Underdog side reuses the favorite price path (underdog price = 1 - favorite),
    flipping entry and outcome. ``ev_no_bracket_reference`` is the pure
    hold-to-settlement EV for the band+side; ``is_argmax`` flags the best bracket.
    """
    required = {band_col, entry_col, outcome_col, fav_team_col, "date", "match_id", "sport"}
    if dataset.empty or not required.issubset(dataset.columns):
        return {s: pd.DataFrame(columns=list(BRACKET_GRID_COLUMNS)) for s in sides}

    fee = float(getattr(settings, "stop_loss_fee_bps", 0.0)) / 10000.0
    slippage = float(getattr(settings, "stop_loss_slippage_bps", 0.0)) / 10000.0
    paths = _collect_paths(
        data_dir, settings, dataset, band_col, entry_col, outcome_col, fav_team_col, base_records_cache_dir
    )
    return {
        s: _grid_from_paths(paths, s, fee, slippage, stop_step, target_step) for s in sides
    }


def build_band_bracket_ev_grid(
    data_dir: str,
    settings,
    dataset: pd.DataFrame,
    band_col: str = "tipoff_interpretable_band",
    entry_col: str = "tipoff_favorite_avg_last_n_pretip_price",
    outcome_col: str = "tipoff_favorite_won",
    fav_team_col: str = "tipoff_favorite_team",
    stop_step: float = 0.02,
    target_step: float = 0.02,
    side: str = "favorite",
    base_records_cache_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Single-side per-band TP×SL bracket EV grid (favorite or underdog)."""
    return build_band_bracket_ev_grids(
        data_dir,
        settings,
        dataset,
        sides=(side,),
        band_col=band_col,
        entry_col=entry_col,
        outcome_col=outcome_col,
        fav_team_col=fav_team_col,
        stop_step=stop_step,
        target_step=target_step,
        base_records_cache_dir=base_records_cache_dir,
    )[side]
