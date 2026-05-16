"""Band x drop-pct recovery aggregator.

Consumes the per-position DataFrame produced by ``backtest.runner.run`` for the
``band_drop_recovery_sweep`` scenario and joins it against the cached base-records
frame to compute conditional base rates:

    Given the favorite was in band B at tipoff and its price dropped X% intraday,
    what fraction of those games saw the price recover to >= the tipoff price
    before game end?

Notes
-----
- Sibling to ``dip_recovery.py``; no shared cache files; no imports from it.
- ``reversion_to_open`` is named for its historical anchor; with anchor="tipoff"
  the exit reverts to the tipoff price (it reads ``trigger.anchor_price``,
  which the trigger sets from whatever it anchored on). That is the
  recovery-to-tipoff semantic this module relies on.
- PnL / fee / ROI columns are intentionally discarded.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from nba_analysis import _wilson_interval


SWEEP_DROP_COL = "sweep_axis_trigger.params.drop_pct"
SUCCESS_EXIT_KIND = "reversion"


def _empty_grid(active_bands: Sequence[str], drop_pcts: Sequence[float]) -> pd.DataFrame:
    return pd.DataFrame(
        index=pd.Index(list(active_bands), name="band"),
        columns=[float(d) for d in drop_pcts],
        dtype=object,
    )


def _empty_detail() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "band",
            "drop_pct",
            "n",
            "successes",
            "recovery_rate",
            "wilson_lo",
            "wilson_hi",
            "median_time_to_recovery_seconds",
            "median_further_drawdown_pct",
        ]
    )


def compute_recovery_grid(
    positions_df: pd.DataFrame,
    base_records_frame: pd.DataFrame,
    active_bands: Sequence[str],
    drop_pcts: Sequence[float],
    *,
    min_n_display: int = 5,
) -> dict[str, pd.DataFrame]:
    """Compute the conditional band x drop-pct recovery grid + detail rows.

    Parameters
    ----------
    positions_df : DataFrame
        Engine output (per-position rows) for the sweep scenario.
    base_records_frame : DataFrame
        Must contain columns ``date``, ``match_id``, ``open_interpretable_band``.
    active_bands : sequence of str
        Bands rendered (canonical order, excluding Toss-Up).
    drop_pcts : sequence of float
        Drop-pct buckets rendered.

    Returns
    -------
    {"grid": wide pivot DataFrame, "detail": long-form DataFrame}
    """
    if positions_df is None or positions_df.empty:
        return {"grid": _empty_grid(active_bands, drop_pcts), "detail": _empty_detail()}

    needed_base = {"date", "match_id", "open_interpretable_band"}
    missing = needed_base - set(base_records_frame.columns)
    if missing:
        raise ValueError(f"base_records_frame missing columns: {sorted(missing)}")

    if SWEEP_DROP_COL not in positions_df.columns:
        raise ValueError(
            f"positions_df missing sweep column {SWEEP_DROP_COL!r}; "
            "ensure the band_drop_recovery_sweep scenario was used."
        )

    joined = positions_df.merge(
        base_records_frame[["date", "match_id", "open_interpretable_band"]],
        on=["date", "match_id"],
        how="left",
    )
    joined = joined[joined["open_interpretable_band"].notna()].copy()
    joined = joined[joined["open_interpretable_band"] != "Toss-Up"].copy()

    drop_series = pd.to_numeric(joined[SWEEP_DROP_COL], errors="coerce")
    joined = joined.assign(drop_pct=drop_series)
    joined = joined[joined["drop_pct"].notna()].copy()

    entry_price = pd.to_numeric(joined["entry_price"], errors="coerce")
    drawdown_cents = (
        pd.to_numeric(joined.get("max_drawdown_cents"), errors="coerce")
        .fillna(0.0)
        .clip(lower=0.0)
    )
    min_price_post_entry = entry_price - (drawdown_cents / 100.0)
    further = (entry_price - min_price_post_entry) / entry_price
    joined["further_drawdown_pct"] = further.where(entry_price > 0, np.nan)

    entry_time = pd.to_datetime(joined["entry_time"], errors="coerce")
    exit_time = pd.to_datetime(joined["exit_time"], errors="coerce")
    joined["time_to_recovery_seconds"] = (
        (exit_time - entry_time).dt.total_seconds()
    )

    detail_rows: list[dict[str, Any]] = []
    grid = _empty_grid(active_bands, drop_pcts)

    for band in active_bands:
        for drop in drop_pcts:
            drop_f = float(drop)
            group = joined[
                (joined["open_interpretable_band"] == band)
                & (joined["drop_pct"] == drop_f)
            ]
            n = int(len(group))
            if n == 0:
                detail_rows.append(
                    {
                        "band": band,
                        "drop_pct": drop_f,
                        "n": 0,
                        "successes": 0,
                        "recovery_rate": None,
                        "wilson_lo": None,
                        "wilson_hi": None,
                        "median_time_to_recovery_seconds": None,
                        "median_further_drawdown_pct": None,
                    }
                )
                grid.at[band, drop_f] = {"n": 0, "rate": None}
                continue

            successes = int((group["exit_kind"] == SUCCESS_EXIT_KIND).sum())
            rate = successes / n
            wlo, whi = _wilson_interval(rate, n)
            recovered = group[group["exit_kind"] == SUCCESS_EXIT_KIND]
            ttr_seconds = (
                float(recovered["time_to_recovery_seconds"].median())
                if not recovered.empty
                else None
            )
            mdd = group["further_drawdown_pct"].median()
            mdd_val = None if pd.isna(mdd) else float(mdd)

            detail_rows.append(
                {
                    "band": band,
                    "drop_pct": drop_f,
                    "n": n,
                    "successes": successes,
                    "recovery_rate": rate,
                    "wilson_lo": wlo,
                    "wilson_hi": whi,
                    "median_time_to_recovery_seconds": ttr_seconds,
                    "median_further_drawdown_pct": mdd_val,
                }
            )
            grid.at[band, drop_f] = {
                "n": n,
                "rate": rate,
                "low_n": 0 < n < min_n_display,
            }

    detail_df = pd.DataFrame(detail_rows, columns=_empty_detail().columns)
    return {"grid": grid, "detail": detail_df}


def compute_band_totals(
    base_records_frame: pd.DataFrame,
    valid_match_ids: Iterable[tuple[str, str]] | None = None,
) -> pd.DataFrame:
    """Per-band denominators across the filtered universe.

    Restricted to games with a valid favorite tipoff price (``tipoff_favorite_price``
    notna) so the totals match what the engine sweep actually sees.
    """
    if base_records_frame is None or base_records_frame.empty:
        return pd.DataFrame(columns=["band", "n"])

    frame = base_records_frame
    if valid_match_ids is not None:
        keep = set((str(d), str(m)) for d, m in valid_match_ids)
        frame = frame[
            frame.apply(lambda r: (str(r["date"]), str(r["match_id"])) in keep, axis=1)
        ]
    tipoff_col = "tipoff_favorite_price"
    if tipoff_col in frame.columns:
        frame = frame[pd.to_numeric(frame[tipoff_col], errors="coerce").notna()]
    if "open_interpretable_band" not in frame.columns:
        return pd.DataFrame(columns=["band", "n"])
    counts = (
        frame["open_interpretable_band"]
        .dropna()
        .value_counts()
        .rename_axis("band")
        .reset_index(name="n")
    )
    return counts


def partition_games(
    base_records_frame: pd.DataFrame,
    filters: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply page-level filters to base_records_frame and report the partition.

    Filters supported (all optional):
      - sport: str (default "nba")
      - start_date / end_date: str (inclusive)
      - price_quality: str (e.g., "live", "all")
      - min_open_favorite_price: float

    Returns
    -------
    {
      "total": int,                      # games in the post-sport/date/quality frame
      "excluded_missing_tipoff": int,    # of those, games dropped for NaN tipoff price
      "kept_match_ids": set[(date, match_id)],
    }
    """
    if base_records_frame is None or base_records_frame.empty:
        return {"total": 0, "excluded_missing_tipoff": 0, "kept_match_ids": set()}

    frame = base_records_frame
    sport = filters.get("sport", "nba")
    if sport and "sport" in frame.columns:
        frame = frame[frame["sport"] == sport]
    if "start_date" in filters and filters["start_date"] is not None and "date" in frame.columns:
        frame = frame[frame["date"] >= filters["start_date"]]
    if "end_date" in filters and filters["end_date"] is not None and "date" in frame.columns:
        frame = frame[frame["date"] <= filters["end_date"]]
    price_quality = filters.get("price_quality")
    if price_quality and price_quality != "all" and "price_quality" in frame.columns:
        frame = frame[frame["price_quality"] == price_quality]
    min_price = filters.get("min_open_favorite_price")
    if min_price is not None and "open_favorite_price" in frame.columns:
        open_fav = pd.to_numeric(frame["open_favorite_price"], errors="coerce")
        frame = frame[open_fav >= float(min_price)]

    total = int(len(frame))
    tipoff_col = "tipoff_favorite_price"
    if tipoff_col in frame.columns:
        tipoff_vals = pd.to_numeric(frame[tipoff_col], errors="coerce")
        with_tipoff = frame[tipoff_vals.notna()]
    else:
        with_tipoff = frame
    excluded = total - int(len(with_tipoff))
    kept = set(
        (str(r["date"]), str(r["match_id"]))
        for _, r in with_tipoff[["date", "match_id"]].iterrows()
    )
    return {
        "total": total,
        "excluded_missing_tipoff": excluded,
        "kept_match_ids": kept,
    }
