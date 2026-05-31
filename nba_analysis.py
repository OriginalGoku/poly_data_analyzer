"""Reusable NBA open-vs-tip-off analysis services and figures."""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache, partial
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from analytics import (
    ACTIVE_INTERPRETABLE_BAND_LABELS,
    INTERPRETABLE_BAND_LABELS,
    TIE_TOLERANCE,
    build_game_analytics_dataset,
    get_analytics_view,
    stream_game_analytics,
)
from loaders import _derive_nba_final_winner, load_game
from settings import ChartSettings


GROUPING_OPTIONS = {
    "open_interpretable_band": "Open Interpretable Band",
    "tipoff_interpretable_band": "Tip-Off Interpretable Band",
    "interpretable_transition": "Interpretable Band Transition",
    "open_quantile_band": "Open Quantile Band",
    "tipoff_quantile_band": "Tip-Off Quantile Band",
    "quantile_transition": "Quantile Band Transition",
    "price_quality": "Price Quality",
    "favorite_outcome_group": "Favorite Outcome Group",
}
GROUP_ORDERINGS = {
    "open_interpretable_band": INTERPRETABLE_BAND_LABELS,
    "tipoff_interpretable_band": INTERPRETABLE_BAND_LABELS,
}


@dataclass(frozen=True)
class AnalysisFilters:
    """Filter values applied to the reusable dataset."""

    price_quality: str = "all"
    start_date: str | None = None
    end_date: str | None = None


@dataclass(frozen=True)
class NBAOpenTipoffSummary:
    """High-level totals shown on the analysis page."""

    games: int
    dropped_open_filter_games: int
    outcome_games: int
    open_prediction_games: int
    tipoff_prediction_games: int
    open_to_tipoff_swing_rate: float | None
    any_pregame_switch_rate: float | None
    open_to_game_end_switch_rate: float | None
    any_in_game_switch_rate: float | None
    open_favorite_win_rate: float | None
    tipoff_favorite_win_rate: float | None
    mean_open_favorite_in_game_min_price: float | None
    mean_open_favorite_max_adverse_excursion: float | None
    mean_open_favorite_max_adverse_excursion_pct: float | None
    mean_abs_move: float | None
    mean_path_volatility: float | None


@dataclass(frozen=True)
class PreparedAnalysisDataset:
    """Dataset plus metadata about dropped rows from the active filter set."""

    dataset: pd.DataFrame
    dropped_open_filter_games: int = 0


class PregameFavoritePathAnalyzer:
    """Compute pregame path-level favorite metrics from raw trades/events."""

    PATH_RESAMPLE_FREQ = "5min"
    SWITCH_MARGIN = 0.015
    SWITCH_PERSISTENCE = 2

    def __init__(self, settings: ChartSettings):
        self.settings = settings

    def compute_metrics(self, trades_df: pd.DataFrame, events: list[dict] | None) -> dict[str, Any]:
        tipoff_time = self._get_tipoff_time(events)
        if tipoff_time is None:
            return self._empty_metrics()

        pregame = trades_df[trades_df["datetime"] < tipoff_time].copy()
        if pregame.empty:
            return self._empty_metrics()

        filtered = self._filter_by_min_cum_vol(pregame)
        if filtered.empty:
            return self._empty_metrics()

        favorite_path = self._build_favorite_path(filtered)
        if favorite_path.empty:
            return self._empty_metrics()

        favorite_returns = favorite_path["favorite_price"].diff().dropna()
        switch_count = self._count_durable_switches(favorite_path)
        spike_count = self._count_volume_spikes(filtered)

        duration_min = (
            (favorite_path.index.max() - favorite_path.index.min()).total_seconds() / 60
            if len(favorite_path.index) > 1
            else 0.0
        )

        return {
            "pregame_path_points": int(len(favorite_path)),
            "pregame_path_start": favorite_path.index.min(),
            "pregame_path_end": favorite_path.index.max(),
            "pregame_duration_min": duration_min,
            "favorite_switch_count_pregame": switch_count,
            "any_favorite_switch_pregame": switch_count > 0,
            "favorite_price_volatility": _safe_std(favorite_returns),
            "favorite_price_realized_volatility": _safe_rms(favorite_returns),
            "favorite_price_range": _safe_range(favorite_path["favorite_price"]),
            "favorite_mean_abs_return": _safe_mean(favorite_returns.abs()),
            "pregame_volume_spike_count": spike_count,
        }

    def _empty_metrics(self) -> dict[str, Any]:
        return {
            "pregame_path_points": 0,
            "pregame_path_start": None,
            "pregame_path_end": None,
            "pregame_duration_min": None,
            "favorite_switch_count_pregame": 0,
            "any_favorite_switch_pregame": False,
            "favorite_price_volatility": None,
            "favorite_price_realized_volatility": None,
            "favorite_price_range": None,
            "favorite_mean_abs_return": None,
            "pregame_volume_spike_count": 0,
        }

    def _get_tipoff_time(self, events: list[dict] | None):
        if not events:
            return None
        for event in events:
            dt = event.get("time_actual_dt")
            if dt is not None:
                return dt
        return None

    def _filter_by_min_cum_vol(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        min_vol = self.settings.pregame_min_cum_vol
        sorted_df = trades_df.sort_values("datetime")
        if sorted_df.empty or min_vol <= 0:
            return sorted_df
        cumulative = sorted_df["size"].cumsum()
        mask = cumulative >= min_vol
        if not mask.any():
            return sorted_df
        return sorted_df.loc[mask]

    def _build_favorite_path(self, filtered: pd.DataFrame) -> pd.DataFrame:
        pivoted = (
            filtered.pivot_table(index="datetime", columns="team", values="price", aggfunc="last")
            .sort_index()
            .ffill()
        )
        if pivoted.empty or len(pivoted.columns) < 2:
            return pd.DataFrame()

        resampled = pivoted.resample(self.PATH_RESAMPLE_FREQ).last().ffill()
        pivoted = resampled.dropna()
        if pivoted.empty:
            return pd.DataFrame()

        teams = list(pivoted.columns[:2])
        favorite_teams: list[str] = []
        favorite_prices: list[float] = []
        for _, row in pivoted.iterrows():
            team_a, team_b = teams[0], teams[1]
            price_a = float(row[team_a])
            price_b = float(row[team_b])
            if abs(price_a - price_b) <= TIE_TOLERANCE:
                favorite_teams.append("Tie")
                favorite_prices.append(price_a)
            elif price_a > price_b:
                favorite_teams.append(team_a)
                favorite_prices.append(price_a)
            else:
                favorite_teams.append(team_b)
                favorite_prices.append(price_b)

        path = pivoted.copy()
        path["favorite_team"] = favorite_teams
        path["favorite_price"] = favorite_prices
        path["favorite_margin"] = (pivoted[teams[0]] - pivoted[teams[1]]).abs()
        return path

    def _count_durable_switches(self, favorite_path: pd.DataFrame) -> int:
        if favorite_path.empty:
            return 0

        switch_count = 0
        current_team = None
        pending_team = None
        pending_count = 0

        for row in favorite_path.itertuples():
            candidate_team = row.favorite_team
            margin = row.favorite_margin

            if current_team is None:
                if candidate_team == "Tie":
                    continue
                current_team = candidate_team
                continue

            if candidate_team in (None, "Tie") or margin < self.SWITCH_MARGIN:
                pending_team = None
                pending_count = 0
                continue

            if candidate_team == current_team:
                pending_team = None
                pending_count = 0
                continue

            if candidate_team != pending_team:
                pending_team = candidate_team
                pending_count = 1
            else:
                pending_count += 1

            if pending_count >= self.SWITCH_PERSISTENCE:
                switch_count += 1
                current_team = candidate_team
                pending_team = None
                pending_count = 0

        return switch_count

    def _count_volume_spikes(self, filtered: pd.DataFrame) -> int:
        sorted_df = filtered.sort_values("datetime")
        if sorted_df.empty:
            return 0

        span = (sorted_df["datetime"].max() - sorted_df["datetime"].min()).total_seconds()
        frequency = "1min" if span < 6 * 3600 else "5min"
        bucketed = sorted_df.set_index("datetime")["size"].resample(frequency).sum().fillna(0)
        if len(bucketed) < self.settings.vol_spike_lookback:
            return 0

        rolling_mean = bucketed.rolling(self.settings.vol_spike_lookback, min_periods=1).mean()
        rolling_std = bucketed.rolling(self.settings.vol_spike_lookback, min_periods=1).std().fillna(0)
        threshold = rolling_mean + self.settings.vol_spike_std * rolling_std
        return int((bucketed > threshold).sum())


class NBAOpenTipoffAnalysisService:
    """Reusable service used by the Dash page and export script."""

    def __init__(
        self,
        data_dir: str = "data",
        settings: ChartSettings | None = None,
        cache_dir: str | None = "cache",
    ):
        self.data_dir = str(Path(data_dir))
        self.settings = settings or ChartSettings()
        self.path_analyzer = PregameFavoritePathAnalyzer(self.settings)
        self.cache_dir = cache_dir

    def load_dataset(self, filters: AnalysisFilters, progress_observer=None) -> pd.DataFrame:
        return self.prepare_dataset(filters, progress_observer=progress_observer).dataset

    def prepare_dataset(self, filters: AnalysisFilters, progress_observer=None) -> PreparedAnalysisDataset:
        if progress_observer is None:
            dataset = _load_nba_analysis_dataset(
                self.data_dir,
                self.settings.pregame_min_cum_vol,
                self.settings.open_anchor_stat,
                self.settings.open_anchor_window_min,
                self.settings.vol_spike_std,
                self.settings.vol_spike_lookback,
                filters.start_date,
                filters.end_date,
                self.cache_dir,
            ).copy()
        else:
            dataset = _build_nba_analysis_dataset(
                self.data_dir,
                self.settings.pregame_min_cum_vol,
                self.settings.open_anchor_stat,
                self.settings.open_anchor_window_min,
                self.settings.vol_spike_std,
                self.settings.vol_spike_lookback,
                filters.start_date,
                filters.end_date,
                progress_observer=progress_observer,
                cache_dir=self.cache_dir,
            )

        if dataset.empty:
            return PreparedAnalysisDataset(dataset, 0)

        start_date = filters.start_date
        end_date = filters.end_date
        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date

        if filters.price_quality != "all":
            dataset = dataset[dataset["price_quality"] == filters.price_quality].copy()
        if start_date:
            dataset = dataset[dataset["date"] >= start_date].copy()
        if end_date:
            dataset = dataset[dataset["date"] <= end_date].copy()
        dropped_games = self._count_dropped_open_filter_games(dataset)
        dataset = dataset[~self._drop_open_filter_mask(dataset)].copy()
        dataset = dataset.sort_values(["date", "match_id"]).reset_index(drop=True)
        return PreparedAnalysisDataset(dataset, dropped_games)

    def build_summary(self, dataset: pd.DataFrame, dropped_open_filter_games: int = 0) -> NBAOpenTipoffSummary:
        if dataset.empty:
            return NBAOpenTipoffSummary(
                0,
                dropped_open_filter_games,
                0,
                0,
                0,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )

        return NBAOpenTipoffSummary(
            games=len(dataset),
            dropped_open_filter_games=dropped_open_filter_games,
            outcome_games=_safe_true_count(dataset["has_outcome"]),
            open_prediction_games=_safe_true_count(dataset["open_prediction_available"]),
            tipoff_prediction_games=_safe_true_count(dataset["tipoff_prediction_available"]),
            open_to_tipoff_swing_rate=_safe_mean(dataset["favorite_changed_open_to_tipoff"].astype(float)),
            any_pregame_switch_rate=_safe_mean(dataset["any_favorite_switch_pregame"].astype(float)),
            open_to_game_end_switch_rate=_safe_mean(
                dataset["favorite_changed_open_to_game_end"].astype(float)
            ),
            any_in_game_switch_rate=_safe_mean(dataset["any_favorite_switch_ingame"].astype(float)),
            open_favorite_win_rate=_nullable_bool_rate(dataset["open_favorite_won"]),
            tipoff_favorite_win_rate=_nullable_bool_rate(dataset["tipoff_favorite_won"]),
            mean_open_favorite_in_game_min_price=_safe_mean(dataset["open_favorite_in_game_min_price"]),
            mean_open_favorite_max_adverse_excursion=_safe_mean(
                dataset["open_favorite_max_adverse_excursion"]
            ),
            mean_open_favorite_max_adverse_excursion_pct=_safe_mean(
                dataset["open_favorite_max_adverse_excursion_pct"]
            ),
            mean_abs_move=_safe_mean(dataset["favorite_move_abs"]),
            mean_path_volatility=_safe_mean(dataset["favorite_price_realized_volatility"]),
        )

    def _drop_open_filter_mask(self, dataset: pd.DataFrame) -> pd.Series:
        if dataset.empty:
            return pd.Series(dtype=bool)
        min_price = float(self.settings.analysis_min_open_favorite_price)
        open_price = pd.to_numeric(dataset["open_favorite_price"], errors="coerce")
        tie_or_missing = dataset["open_favorite_team"].isna() | (dataset["open_favorite_team"] == "Tie")
        below_floor = open_price.isna() | (open_price < min_price)
        return tie_or_missing | below_floor

    def _count_dropped_open_filter_games(self, dataset: pd.DataFrame) -> int:
        return int(self._drop_open_filter_mask(dataset).sum())

    def build_group_summary(self, dataset: pd.DataFrame, group_by: str) -> pd.DataFrame:
        if dataset.empty:
            return pd.DataFrame()

        grouped = dataset.groupby(group_by, dropna=False)
        summary = grouped.agg(
            games=("match_id", "count"),
            outcome_games=("has_outcome", _safe_true_count),
            open_prediction_games=("open_prediction_available", _safe_true_count),
            tipoff_prediction_games=("tipoff_prediction_available", _safe_true_count),
            open_to_tipoff_swing_rate=("favorite_changed_open_to_tipoff", lambda s: float(pd.Series(s).mean())),
            any_pregame_switch_rate=("any_favorite_switch_pregame", lambda s: float(pd.Series(s).mean())),
            open_to_game_end_switch_rate=("favorite_changed_open_to_game_end", lambda s: float(pd.Series(s).mean())),
            any_in_game_switch_rate=("any_favorite_switch_ingame", lambda s: float(pd.Series(s).mean())),
            open_favorite_win_rate=("open_favorite_won", _nullable_bool_rate),
            tipoff_favorite_win_rate=("tipoff_favorite_won", _nullable_bool_rate),
            mean_open_favorite_in_game_min_price=("open_favorite_in_game_min_price", "mean"),
            median_open_favorite_in_game_min_price=("open_favorite_in_game_min_price", "median"),
            mean_open_favorite_in_game_max_price=("open_favorite_in_game_max_price", "mean"),
            mean_open_favorite_max_adverse_excursion=("open_favorite_max_adverse_excursion", "mean"),
            mean_open_favorite_max_adverse_excursion_pct=(
                "open_favorite_max_adverse_excursion_pct",
                "mean",
            ),
            mean_open_favorite_max_favorable_excursion=(
                "open_favorite_max_favorable_excursion",
                "mean",
            ),
            mean_open_favorite_max_favorable_excursion_pct=(
                "open_favorite_max_favorable_excursion_pct",
                "mean",
            ),
            mean_signed_move=("favorite_move_signed", "mean"),
            median_signed_move=("favorite_move_signed", "median"),
            mean_abs_move=("favorite_move_abs", "mean"),
            mean_realized_volatility=("favorite_price_realized_volatility", "mean"),
            mean_switch_count=("favorite_switch_count_pregame", "mean"),
            mean_volume_spikes=("pregame_volume_spike_count", "mean"),
        ).reset_index()
        total_games = int(summary["games"].sum())
        summary["games_share"] = summary["games"] / total_games if total_games else 0.0

        summary["open_to_tipoff_swing_ci_low"] = summary.apply(
            lambda row: _wilson_interval(row["open_to_tipoff_swing_rate"], int(row["games"]))[0],
            axis=1,
        )
        summary["open_to_tipoff_swing_ci_high"] = summary.apply(
            lambda row: _wilson_interval(row["open_to_tipoff_swing_rate"], int(row["games"]))[1],
            axis=1,
        )
        ordered = _order_grouped_frame(summary, group_by)
        if ordered is not None:
            return ordered.reset_index(drop=True)
        return summary.sort_values("games", ascending=False).reset_index(drop=True)

    PERCENTILE_GRID = (5, 10, 25, 50, 75, 90, 95)
    _DISTRIBUTION_COLUMNS = (
        "band",
        "outcome",
        "n_games",
        "p05",
        "p10",
        "p25",
        "p50",
        "p75",
        "p90",
        "p95",
    )

    def build_band_outcome_distribution(
        self,
        dataset: pd.DataFrame,
        band_col: str = "tipoff_interpretable_band",
        value_col: str = "tipoff_favorite_in_game_min_price",
    ) -> pd.DataFrame:
        """Per-(band, outcome) percentile distribution of ``value_col``.

        Long-form: one row per ``(band, win|loss)``. Games with a null
        ``tipoff_favorite_won`` (no derivable outcome) are excluded. Honors the
        ``GROUP_ORDERINGS`` band ordering when defined.
        """
        cols = list(self._DISTRIBUTION_COLUMNS)
        pct_keys = ["p05", "p10", "p25", "p50", "p75", "p90", "p95"]
        if (
            dataset.empty
            or band_col not in dataset
            or value_col not in dataset
            or "tipoff_favorite_won" not in dataset
        ):
            return pd.DataFrame(columns=cols)

        df = dataset[dataset["tipoff_favorite_won"].notna()]
        if df.empty:
            return pd.DataFrame(columns=cols)

        rows = []
        for (band, won), group in df.groupby([band_col, "tipoff_favorite_won"], dropna=True):
            values = pd.to_numeric(group[value_col], errors="coerce").to_numpy(dtype=float)
            values = values[~np.isnan(values)]
            n_games = int(len(values))
            row = {
                "band": band,
                "outcome": "win" if bool(won) else "loss",
                "n_games": n_games,
            }
            if n_games:
                pcts = np.nanpercentile(values, list(self.PERCENTILE_GRID))
                row.update({key: float(p) for key, p in zip(pct_keys, pcts)})
            else:
                row.update({key: None for key in pct_keys})
            rows.append(row)

        result = pd.DataFrame(rows, columns=cols)
        ordering = GROUP_ORDERINGS.get(band_col)
        if ordering and not result.empty:
            present = [label for label in ordering if label in set(result["band"])]
            result["band"] = pd.Categorical(result["band"], categories=present, ordered=True)
            result = result.sort_values(["band", "outcome"]).reset_index(drop=True)
            result["band"] = result["band"].astype(str)
        return result

    _EV_GRID_COLUMNS = (
        "band",
        "stop_price",
        "entry_price_used",
        "n_games",
        "win_stopout_rate",
        "win_stopout_ci_low",
        "win_stopout_ci_high",
        "loss_stopout_rate",
        "loss_stopout_ci_low",
        "loss_stopout_ci_high",
        "ev_per_unit_stake",
        "ev_no_stop_reference",
        "is_argmax",
    )

    @staticmethod
    def _stopout_rate_ci(min_prices: np.ndarray, stop: float):
        """``P(min_price <= stop)`` plus Wilson CI over the non-null subset."""
        arr = min_prices[~np.isnan(min_prices)]
        n = int(len(arr))
        if n == 0:
            return 0.0, None, None
        rate = float(np.mean(arr <= stop))
        lo, hi = _wilson_interval(rate, n)
        return rate, lo, hi

    def build_band_stop_loss_ev_grid(
        self,
        dataset: pd.DataFrame,
        settings: ChartSettings,
        band_col: str = "tipoff_interpretable_band",
        entry_col: str = "tipoff_favorite_avg_last_n_pretip_price",
        min_price_col: str = "tipoff_favorite_in_game_min_price",
        outcome_col: str = "tipoff_favorite_won",
        stop_grid: tuple[float, ...] | None = None,
    ) -> pd.DataFrame:
        """EV-vs-stop-price grid per band for a long-favorite tip-off entry.

        Long-form: one row per ``(band, stop_price)``. ``entry_price_used`` is a
        single band-level mean entry ``E``; ``ev_no_stop_reference`` is constant
        within a band; ``is_argmax`` flags the EV-maximizing stop per band.

        Only stops *below* the band entry ``E`` are evaluated (plus the
        ``stop_price = 0.0`` no-stop reference). A stop at or above entry would
        trigger on essentially every game under the ``min_price <= stop`` model
        (price starts at ~E), modelling an instant exit near entry and
        producing a spurious argmax — so those stops are excluded.

        NOTE: ``min_price`` comes from a 5-minute resample (see
        ``PregameFavoritePathAnalyzer.PATH_RESAMPLE_FREQ``); a stop touched
        between bars may be missed, so EV here is an upper-bound estimate.
        """
        cols = list(self._EV_GRID_COLUMNS)
        required = {band_col, entry_col, min_price_col, outcome_col}
        if dataset.empty or not required.issubset(dataset.columns):
            return pd.DataFrame(columns=cols)

        if stop_grid is None:
            stop_grid = tuple(round(float(x), 4) for x in np.arange(0.0, 0.99, 0.01))

        fee = float(getattr(settings, "stop_loss_fee_bps", 0.0)) / 10000.0
        slippage = float(getattr(settings, "stop_loss_slippage_bps", 0.0)) / 10000.0

        rows = []
        for band, group in dataset.groupby(band_col, dropna=True):
            valid = group[group[outcome_col].notna()]
            if valid.empty:
                continue
            entry_rows = valid[valid[entry_col].notna()]
            if entry_rows.empty:
                continue
            E = float(pd.to_numeric(entry_rows[entry_col], errors="coerce").mean())
            if np.isnan(E):
                continue

            outcomes = valid[outcome_col].astype(bool)
            n_games = int(len(valid))
            win_rate = float(outcomes.mean())
            loss_rate = 1.0 - win_rate
            winners_min = pd.to_numeric(
                valid.loc[outcomes, min_price_col], errors="coerce"
            ).to_numpy(dtype=float)
            losers_min = pd.to_numeric(
                valid.loc[~outcomes, min_price_col], errors="coerce"
            ).to_numpy(dtype=float)
            n_win = int(np.count_nonzero(~np.isnan(winners_min)))
            n_loss = int(np.count_nonzero(~np.isnan(losers_min)))

            ev_no_stop = win_rate * (1.0 - E) + loss_rate * (-E) - fee

            # Restrict to stops below entry; always keep the 0.0 no-stop row.
            band_grid = [stop for stop in stop_grid if stop <= 0.0 or stop < E]

            band_rows = []
            for stop in band_grid:
                stop_fill = stop - slippage
                if stop <= 0.0:
                    # No-stop reference: a stop at 0 is never triggered.
                    wsr, (wlo, whi) = 0.0, _wilson_interval(0.0, n_win)
                    lsr, (llo, lhi) = 0.0, _wilson_interval(0.0, n_loss)
                    ev = ev_no_stop
                else:
                    wsr, wlo, whi = self._stopout_rate_ci(winners_min, stop)
                    lsr, llo, lhi = self._stopout_rate_ci(losers_min, stop)
                    ev = (
                        win_rate
                        * ((1.0 - wsr) * (1.0 - E) + wsr * (stop_fill - E))
                        + loss_rate
                        * ((1.0 - lsr) * (0.0 - E) + lsr * (stop_fill - E))
                        - fee
                    )
                band_rows.append(
                    {
                        "band": band,
                        "stop_price": float(stop),
                        "entry_price_used": E,
                        "n_games": n_games,
                        "win_stopout_rate": wsr,
                        "win_stopout_ci_low": wlo,
                        "win_stopout_ci_high": whi,
                        "loss_stopout_rate": lsr,
                        "loss_stopout_ci_low": llo,
                        "loss_stopout_ci_high": lhi,
                        "ev_per_unit_stake": ev,
                        "ev_no_stop_reference": ev_no_stop,
                        "is_argmax": False,
                    }
                )

            if band_rows:
                best = max(range(len(band_rows)), key=lambda i: band_rows[i]["ev_per_unit_stake"])
                band_rows[best]["is_argmax"] = True
                rows.extend(band_rows)

        result = pd.DataFrame(rows, columns=cols)
        ordering = GROUP_ORDERINGS.get(band_col)
        if ordering and not result.empty:
            present = [label for label in ordering if label in set(result["band"])]
            result["band"] = pd.Categorical(result["band"], categories=present, ordered=True)
            result = result.sort_values(["band", "stop_price"]).reset_index(drop=True)
            result["band"] = result["band"].astype(str)
        return result

    def build_transition_outcome_summary(self, dataset: pd.DataFrame) -> pd.DataFrame:
        return self.build_group_summary(dataset, "interpretable_transition")

    def build_coverage_summary(self, dataset: pd.DataFrame, dropped_open_filter_games: int = 0) -> pd.DataFrame:
        games = int(len(dataset))
        outcome_games = _safe_true_count(dataset["has_outcome"]) if not dataset.empty else 0
        open_prediction_games = _safe_true_count(dataset["open_prediction_available"]) if not dataset.empty else 0
        tipoff_prediction_games = _safe_true_count(dataset["tipoff_prediction_available"]) if not dataset.empty else 0
        rows = [
            {"metric": "filtered_games", "count": games, "share_of_filtered_games": 1.0 if games else None},
            {
                "metric": "dropped_open_filter_games",
                "count": int(dropped_open_filter_games),
                "share_of_filtered_games": None,
            },
            {
                "metric": "outcome_games",
                "count": outcome_games,
                "share_of_filtered_games": _safe_share(outcome_games, games),
            },
            {
                "metric": "missing_outcome_games",
                "count": games - outcome_games,
                "share_of_filtered_games": _safe_share(games - outcome_games, games),
            },
            {
                "metric": "open_prediction_games",
                "count": open_prediction_games,
                "share_of_filtered_games": _safe_share(open_prediction_games, games),
            },
            {
                "metric": "missing_open_prediction_games",
                "count": games - open_prediction_games,
                "share_of_filtered_games": _safe_share(games - open_prediction_games, games),
            },
            {
                "metric": "tipoff_prediction_games",
                "count": tipoff_prediction_games,
                "share_of_filtered_games": _safe_share(tipoff_prediction_games, games),
            },
            {
                "metric": "missing_tipoff_prediction_games",
                "count": games - tipoff_prediction_games,
                "share_of_filtered_games": _safe_share(games - tipoff_prediction_games, games),
            },
        ]
        return pd.DataFrame(rows)

    def build_transition_matrix(self, dataset: pd.DataFrame, from_col: str, to_col: str) -> pd.DataFrame:
        if dataset.empty:
            return pd.DataFrame()
        matrix = pd.crosstab(dataset[from_col], dataset[to_col], normalize="index").round(4)
        if from_col in GROUP_ORDERINGS:
            matrix = matrix.reindex([label for label in GROUP_ORDERINGS[from_col] if label in matrix.index])
        if to_col in GROUP_ORDERINGS:
            matrix = matrix.reindex(
                columns=[label for label in GROUP_ORDERINGS[to_col] if label in matrix.columns]
            )
        return matrix

    def figure_builder(self) -> "NBAOpenTipoffFigureBuilder":
        return NBAOpenTipoffFigureBuilder()


class NBAOpenTipoffFigureBuilder:
    """Focused, low-clutter visual set for exploratory analysis."""

    def build_figures(self, dataset: pd.DataFrame, group_by: str) -> dict[str, go.Figure]:
        if dataset.empty:
            return {
                "transition_heatmap": self._empty_figure("No NBA games available for the current filter"),
                "signed_move": self._empty_figure("No signed-move data available"),
                "swing_rates": self._empty_figure("No swing-rate data available"),
                "open_vs_tipoff": self._empty_figure("No open-vs-tipoff data available"),
            }

        return {
            "transition_heatmap": self._build_transition_heatmap(dataset),
            "signed_move": self._build_signed_move_figure(dataset, group_by),
            "swing_rates": self._build_swing_rate_figure(dataset, group_by),
            "open_vs_tipoff": self._build_open_vs_tipoff_scatter(dataset, group_by),
            "volatility": self._build_volatility_figure(dataset, group_by),
        }

    def _build_transition_heatmap(self, dataset: pd.DataFrame) -> go.Figure:
        matrix = (
            pd.crosstab(
                dataset["open_interpretable_band"],
                dataset["tipoff_interpretable_band"],
                normalize="index",
            )
            .reindex(ACTIVE_INTERPRETABLE_BAND_LABELS)
            .reindex(columns=ACTIVE_INTERPRETABLE_BAND_LABELS)
            .fillna(0)
        )
        if matrix.empty:
            return self._empty_figure("No transition data available")

        fig = px.imshow(
            matrix,
            text_auto=".0%",
            color_continuous_scale="Blues",
            aspect="auto",
            labels={"x": "Tip-Off Band", "y": "Open Band", "color": "Share"},
            title="Interpretable Band Transition Heatmap",
        )
        return _apply_dark_theme(fig)

    def _build_signed_move_figure(self, dataset: pd.DataFrame, group_by: str) -> go.Figure:
        ordered = _ordered_group_values(dataset, group_by)
        fig = px.box(
            dataset,
            x=group_by,
            y="favorite_move_signed",
            points="suspectedoutliers",
            color=group_by,
            title=f"Signed Favorite-Probability Move by {GROUPING_OPTIONS[group_by]}",
            labels={
                group_by: GROUPING_OPTIONS[group_by],
                "favorite_move_signed": "Tip-Off Favorite Price - Open Favorite Price",
            },
            category_orders={group_by: ordered} if ordered else None,
        )
        return _apply_dark_theme(fig)

    def _build_swing_rate_figure(self, dataset: pd.DataFrame, group_by: str) -> go.Figure:
        summary = (
            dataset.groupby(group_by, dropna=False)["favorite_changed_open_to_tipoff"]
            .mean()
            .reset_index(name="swing_rate")
        )
        ordered = _order_grouped_frame(summary, group_by)
        if ordered is not None:
            summary = ordered
        else:
            summary = summary.sort_values("swing_rate", ascending=False)
        fig = px.bar(
            summary,
            x=group_by,
            y="swing_rate",
            color="swing_rate",
            color_continuous_scale="Sunset",
            title=f"Favorite Swing Probability by {GROUPING_OPTIONS[group_by]}",
            labels={group_by: GROUPING_OPTIONS[group_by], "swing_rate": "Swing Probability"},
        )
        fig.update_yaxes(tickformat=".0%")
        return _apply_dark_theme(fig)

    def _build_open_vs_tipoff_scatter(self, dataset: pd.DataFrame, group_by: str) -> go.Figure:
        ordered = _ordered_group_values(dataset, group_by)
        fig = px.scatter(
            dataset,
            x="open_favorite_price",
            y="tipoff_favorite_price",
            color=group_by,
            hover_name="label",
            title=f"Open vs Tip-Off Favorite Price by {GROUPING_OPTIONS[group_by]}",
            labels={
                "open_favorite_price": "Open Favorite Price",
                "tipoff_favorite_price": "Tip-Off Favorite Price",
                group_by: GROUPING_OPTIONS[group_by],
            },
            category_orders={group_by: ordered} if ordered else None,
        )
        fig.add_shape(
            type="line",
            x0=0,
            x1=1,
            y0=0,
            y1=1,
            line={"color": "#888", "dash": "dash"},
        )
        return _apply_dark_theme(fig)

    def _build_volatility_figure(self, dataset: pd.DataFrame, group_by: str) -> go.Figure:
        ordered = _ordered_group_values(dataset, group_by)
        fig = px.violin(
            dataset,
            x=group_by,
            y="favorite_price_realized_volatility",
            color=group_by,
            box=True,
            points=False,
            title=f"Pregame Realized Volatility by {GROUPING_OPTIONS[group_by]}",
            labels={
                group_by: GROUPING_OPTIONS[group_by],
                "favorite_price_realized_volatility": "Realized Volatility",
            },
            category_orders={group_by: ordered} if ordered else None,
        )
        return _apply_dark_theme(fig)

    def _empty_figure(self, message: str) -> go.Figure:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark",
            annotations=[
                {
                    "text": message,
                    "showarrow": False,
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "font": {"size": 18, "color": "#888"},
                }
            ],
        )
        return fig


@lru_cache(maxsize=8)
def _load_nba_analysis_dataset(
    data_dir: str,
    pregame_min_cum_vol: float,
    open_anchor_stat: str,
    open_anchor_window_min: int,
    vol_spike_std: float,
    vol_spike_lookback: int,
    start_date: str | None,
    end_date: str | None,
    cache_dir: str | None = None,
) -> pd.DataFrame:
    return _build_nba_analysis_dataset(
        data_dir,
        pregame_min_cum_vol,
        open_anchor_stat,
        open_anchor_window_min,
        vol_spike_std,
        vol_spike_lookback,
        start_date,
        end_date,
        progress_observer=None,
        cache_dir=cache_dir,
    )


def _build_nba_analysis_dataset(
    data_dir: str,
    pregame_min_cum_vol: float,
    open_anchor_stat: str,
    open_anchor_window_min: int,
    vol_spike_std: float,
    vol_spike_lookback: int,
    start_date: str | None,
    end_date: str | None,
    progress_observer=None,
    cache_dir: str | None = None,
) -> pd.DataFrame:
    settings = ChartSettings(
        open_anchor_stat=open_anchor_stat,
        open_anchor_window_min=open_anchor_window_min,
        pregame_min_cum_vol=pregame_min_cum_vol,
        vol_spike_std=vol_spike_std,
        vol_spike_lookback=vol_spike_lookback,
    )
    service = NBAOpenTipoffAnalysisService.__new__(NBAOpenTipoffAnalysisService)
    service.data_dir = data_dir
    service.settings = settings
    service.path_analyzer = PregameFavoritePathAnalyzer(settings)

    _t0 = time.perf_counter()
    _t1 = time.perf_counter()
    rows: list[dict[str, Any]] = []
    base_records_list: list[dict[str, Any]] = []
    stream_observer = progress_observer.child("base") if progress_observer is not None else None

    base_records_cache_dir = (
        str(Path(cache_dir) / "_base_records") if cache_dir is not None else None
    )

    detail_started = False
    for index, (base_record, get_game) in enumerate(
        stream_game_analytics(
            data_dir=data_dir,
            pregame_min_cum_vol=pregame_min_cum_vol,
            open_anchor_stat=open_anchor_stat,
            open_anchor_window_min=open_anchor_window_min,
            start_date=start_date,
            end_date=end_date,
            progress_observer=stream_observer,
            base_records_cache_dir=base_records_cache_dir,
        ),
        start=1,
    ):
        if base_record.get("sport") != "nba":
            continue
        base_records_list.append(base_record)
        if not detail_started:
            print(
                f"[nba_tipoff] base_records (streaming) elapsed_so_far={time.perf_counter() - _t0:.1f}s",
                flush=True,
            )
            _t1 = time.perf_counter()
            if progress_observer is not None:
                progress_observer.start(total=0, description="Processing NBA detailed metrics")
            detail_started = True
        if cache_dir is not None:
            from nba_tipoff_cache import load_or_compute_nba_tipoff_detail
            details = load_or_compute_nba_tipoff_detail(
                cache_dir=cache_dir,
                data_dir=data_dir,
                date=base_record["date"],
                match_id=base_record["match_id"],
                game_provider=get_game,
                settings=settings,
                open_favorite_team=base_record.get("open_favorite_team"),
                open_favorite_price=base_record.get("open_favorite_price"),
                compute_fn=partial(
                    _compute_nba_detail_row_from_game,
                    tipoff_favorite_team=base_record.get("tipoff_favorite_team"),
                    tipoff_favorite_price=base_record.get("tipoff_favorite_price"),
                ),
            )
        else:
            details = _compute_nba_detail_row_from_game(
                get_game(),
                settings,
                base_record.get("open_favorite_team"),
                base_record.get("open_favorite_price"),
                base_record.get("tipoff_favorite_team"),
                base_record.get("tipoff_favorite_price"),
            )
        merged = {**base_record, **details}
        merged["favorite_move_signed"] = _compute_signed_move(
            merged.get("open_favorite_price"),
            merged.get("tipoff_favorite_price"),
        )
        merged["favorite_move_abs"] = (
            abs(merged["favorite_move_signed"]) if merged["favorite_move_signed"] is not None else None
        )
        merged["favorite_changed_open_to_tipoff"] = _favorite_changed(
            merged.get("open_favorite_team"),
            merged.get("tipoff_favorite_team"),
        )
        merged["open_prediction_available"] = _prediction_available(
            merged.get("open_favorite_team"),
            merged.get("final_winner"),
        )
        merged["tipoff_prediction_available"] = _prediction_available(
            merged.get("tipoff_favorite_team"),
            merged.get("final_winner"),
        )
        merged["open_favorite_won"] = _favorite_won(
            merged.get("open_favorite_team"),
            merged.get("final_winner"),
        )
        merged["tipoff_favorite_won"] = _favorite_won(
            merged.get("tipoff_favorite_team"),
            merged.get("final_winner"),
        )
        merged["interpretable_transition"] = _build_transition_label(
            merged.get("open_interpretable_band"),
            merged.get("tipoff_interpretable_band"),
        )
        merged["favorite_outcome_group"] = _favorite_outcome_group(
            merged["favorite_changed_open_to_tipoff"],
            merged.get("any_favorite_switch_pregame"),
        )
        rows.append(merged)
        if progress_observer is not None:
            progress_observer.advance(
                index=index, match_id=base_record["match_id"], date=base_record["date"]
            )

    if not rows:
        print(f"[nba_tipoff] base_records=0 elapsed={time.perf_counter() - _t0:.1f}s", flush=True)
        return pd.DataFrame()

    print(
        f"[nba_tipoff] detail_loop games={len(rows)} elapsed={time.perf_counter() - _t1:.1f}s",
        flush=True,
    )
    _t2 = time.perf_counter()
    dataset = pd.DataFrame(rows)
    dataset["date"] = pd.to_datetime(dataset["date"]).dt.strftime("%Y-%m-%d")

    quantiles = _compute_quantiles_for_progress_build(dataset)
    for anchor in ("open", "tipoff"):
        price_col = f"{anchor}_favorite_price"
        band_col = f"{anchor}_quantile_band"
        dataset[band_col] = dataset[price_col].apply(
            lambda p, _q=quantiles.get(anchor): _assign_quantile_band_for_progress_build(p, _q)
        )
    dataset["quantile_transition"] = dataset.apply(
        lambda r: _build_transition_label(
            r.get("open_quantile_band"), r.get("tipoff_quantile_band")
        ),
        axis=1,
    )

    if progress_observer is not None:
        progress_observer.finish(total=len(rows))
    print(
        f"[nba_tipoff] post_process rows={len(dataset)} elapsed={time.perf_counter() - _t2:.1f}s",
        flush=True,
    )
    return dataset


def _compute_quantiles_for_progress_build(df: pd.DataFrame) -> dict[str, tuple[float, float]]:
    thresholds: dict[str, tuple[float, float]] = {}
    for anchor in ("open", "tipoff"):
        prices = df[f"{anchor}_favorite_price"].dropna().astype(float)
        if prices.empty:
            continue
        thresholds[anchor] = (float(prices.quantile(1 / 3)), float(prices.quantile(2 / 3)))
    return thresholds


def _assign_quantile_band_for_progress_build(price: float | None, thresholds: tuple[float, float] | None) -> str | None:
    if price is None or pd.isna(price) or thresholds is None:
        return None
    q1, q2 = thresholds
    if price < q1:
        return "Q1"
    if price < q2:
        return "Q2"
    return "Q3"


def _compute_nba_detail_row_from_game(
    game: dict,
    settings: ChartSettings,
    open_favorite_team: str | None,
    open_favorite_price: float | None,
    tipoff_favorite_team: str | None = None,
    tipoff_favorite_price: float | None = None,
) -> dict[str, Any]:
    """Compute per-game detail metrics from an already-loaded game dict.

    Streaming entry point: avoids the second trades.json.gz read that the
    cached `_load_nba_detail_row` wrapper performs via `load_game`.

    `tipoff_favorite_team` / `tipoff_favorite_price` originate in the base
    record (see `analytics.py`), not in `compute_metrics`; the caller threads
    them in so the tip-off-side in-game path can be measured.
    """
    path_analyzer = PregameFavoritePathAnalyzer(settings)
    details = path_analyzer.compute_metrics(game["trades_df"], game["events"])
    final_winner = _derive_nba_final_winner(game["manifest"], game["events"])
    details.update(
        _compute_in_game_open_favorite_metrics(
            game["trades_df"],
            game["events"],
            game["manifest"],
            settings,
            open_favorite_team,
            open_favorite_price,
            tipoff_favorite_team,
            tipoff_favorite_price,
        )
    )
    tipoff_time = _resolve_score_tipoff_time(game["events"])
    entry_price, n_used = _compute_tipoff_entry_window_price(
        game["trades_df"],
        game["manifest"],
        tipoff_favorite_team,
        tipoff_time,
        int(getattr(settings, "tipoff_entry_window_trades", 0)),
    )
    details.update(
        {
            "final_winner": final_winner,
            "has_outcome": final_winner is not None,
            "tipoff_favorite_avg_last_n_pretip_price": entry_price,
            "tipoff_entry_window_n_used": n_used,
        }
    )
    return details


@lru_cache(maxsize=256)
def _load_nba_detail_row(
    data_dir: str,
    date: str,
    match_id: str,
    pregame_min_cum_vol: float,
    vol_spike_std: float,
    vol_spike_lookback: int,
    open_favorite_team: str | None,
    open_favorite_price: float | None,
) -> dict[str, Any]:
    settings = ChartSettings(
        pregame_min_cum_vol=pregame_min_cum_vol,
        vol_spike_std=vol_spike_std,
        vol_spike_lookback=vol_spike_lookback,
    )
    game = load_game(data_dir, date, match_id)
    return _compute_nba_detail_row_from_game(
        game, settings, open_favorite_team, open_favorite_price
    )


def _favorite_changed(open_team: str | None, tipoff_team: str | None) -> bool:
    if not open_team or not tipoff_team:
        return False
    return open_team != tipoff_team


def _in_game_excursion_metrics(
    price_path: pd.DataFrame,
    team_col: str,
    anchor_price: float | None,
    tipoff_time: pd.Timestamp,
    prefix: str,
) -> dict[str, Any]:
    """Min/max/MAE/MFE for one team side over the in-game price path.

    Shared by the open-favorite and tip-off-favorite branches; `prefix` selects
    the output key namespace (``open_favorite`` or ``tipoff_favorite``).
    """
    out = {
        f"{prefix}_in_game_min_price": None,
        f"{prefix}_in_game_max_price": None,
        f"{prefix}_time_to_min_seconds": None,
        f"{prefix}_time_to_max_seconds": None,
        f"{prefix}_max_adverse_excursion": None,
        f"{prefix}_max_adverse_excursion_pct": None,
        f"{prefix}_max_favorable_excursion": None,
        f"{prefix}_max_favorable_excursion_pct": None,
    }
    team_series = price_path[team_col].dropna()
    if team_series.empty:
        return out
    min_idx = team_series.idxmin()
    max_idx = team_series.idxmax()
    min_price = float(team_series.loc[min_idx])
    max_price = float(team_series.loc[max_idx])
    out[f"{prefix}_in_game_min_price"] = min_price
    out[f"{prefix}_in_game_max_price"] = max_price
    out[f"{prefix}_time_to_min_seconds"] = float((min_idx - tipoff_time).total_seconds())
    out[f"{prefix}_time_to_max_seconds"] = float((max_idx - tipoff_time).total_seconds())
    if anchor_price is not None and not pd.isna(anchor_price):
        anchor = float(anchor_price)
        out[f"{prefix}_max_adverse_excursion"] = max(anchor - min_price, 0.0)
        out[f"{prefix}_max_favorable_excursion"] = max(max_price - anchor, 0.0)
        if anchor > 0:
            out[f"{prefix}_max_adverse_excursion_pct"] = (
                out[f"{prefix}_max_adverse_excursion"] / anchor
            )
            out[f"{prefix}_max_favorable_excursion_pct"] = (
                out[f"{prefix}_max_favorable_excursion"] / anchor
            )
    return out


def _compute_in_game_open_favorite_metrics(
    trades_df: pd.DataFrame,
    events: list[dict] | None,
    manifest: dict,
    settings: ChartSettings,
    open_favorite_team: str | None,
    open_favorite_price: float | None,
    tipoff_favorite_team: str | None = None,
    tipoff_favorite_price: float | None = None,
) -> dict[str, Any]:
    metrics = {
        "last_in_game_favorite_team": None,
        "favorite_changed_open_to_game_end": False,
        "favorite_switch_count_ingame": 0,
        "any_favorite_switch_ingame": False,
        "open_favorite_in_game_min_price": None,
        "open_favorite_in_game_max_price": None,
        "open_favorite_time_to_min_seconds": None,
        "open_favorite_time_to_max_seconds": None,
        "open_favorite_max_adverse_excursion": None,
        "open_favorite_max_adverse_excursion_pct": None,
        "open_favorite_max_favorable_excursion": None,
        "open_favorite_max_favorable_excursion_pct": None,
        "tipoff_favorite_in_game_min_price": None,
        "tipoff_favorite_in_game_max_price": None,
        "tipoff_favorite_time_to_min_seconds": None,
        "tipoff_favorite_time_to_max_seconds": None,
        "tipoff_favorite_max_adverse_excursion": None,
        "tipoff_favorite_max_adverse_excursion_pct": None,
        "tipoff_favorite_max_favorable_excursion": None,
        "tipoff_favorite_max_favorable_excursion_pct": None,
    }
    if not events:
        return metrics

    score_events = [
        event
        for event in events
        if event.get("time_actual_dt") is not None
        and event.get("away_score") is not None
        and event.get("home_score") is not None
    ]
    if not score_events or len(manifest.get("token_ids", [])) < 2 or len(manifest.get("outcomes", [])) < 2:
        return metrics

    tipoff_time = min(event["time_actual_dt"] for event in score_events)
    game_end = max(event["time_actual_dt"] for event in score_events) + pd.Timedelta(
        minutes=float(getattr(settings, "post_game_buffer_min", 10))
    )
    ingame = trades_df[
        (trades_df["datetime"] >= tipoff_time) & (trades_df["datetime"] <= game_end)
    ].sort_values("datetime").copy()
    if ingame.empty:
        return metrics

    away_token = manifest["token_ids"][0]
    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]

    ingame["away_price"] = ingame["price"].astype(float)
    home_mask = ingame["asset"] != away_token
    ingame.loc[home_mask, "away_price"] = 1.0 - ingame.loc[home_mask, "away_price"]
    ingame["home_price"] = 1.0 - ingame["away_price"]
    price_path = (
        ingame.groupby("datetime")[["away_price", "home_price"]]
        .last()
        .sort_index()
        .ffill()
        .dropna()
    )
    if price_path.empty:
        return metrics

    favorite_path = price_path.resample(PregameFavoritePathAnalyzer.PATH_RESAMPLE_FREQ).last().ffill().dropna()
    if favorite_path.empty:
        favorite_path = price_path
    favorite_path = _attach_favorite_columns(favorite_path, away_team, home_team)
    last_in_game_favorite_team = favorite_path.iloc[-1]["favorite_team"] if not favorite_path.empty else None
    switch_counter = PregameFavoritePathAnalyzer(settings)
    favorite_switch_count_ingame = switch_counter._count_durable_switches(favorite_path)

    if open_favorite_team in (away_team, home_team):
        team_col = "away_price" if open_favorite_team == away_team else "home_price"
        metrics.update(
            _in_game_excursion_metrics(
                price_path, team_col, open_favorite_price, tipoff_time, "open_favorite"
            )
        )

    if tipoff_favorite_team in (away_team, home_team):
        team_col = "away_price" if tipoff_favorite_team == away_team else "home_price"
        metrics.update(
            _in_game_excursion_metrics(
                price_path, team_col, tipoff_favorite_price, tipoff_time, "tipoff_favorite"
            )
        )

    metrics["last_in_game_favorite_team"] = last_in_game_favorite_team
    metrics["favorite_changed_open_to_game_end"] = bool(
        open_favorite_team not in (None, "Tie")
        and last_in_game_favorite_team not in (None, "Tie")
        and open_favorite_team != last_in_game_favorite_team
    )
    metrics["favorite_switch_count_ingame"] = favorite_switch_count_ingame
    metrics["any_favorite_switch_ingame"] = favorite_switch_count_ingame > 0
    return metrics


def _resolve_score_tipoff_time(events: list[dict] | None):
    """Tip-off time = earliest score event with a wall-clock timestamp.

    Mirrors the boundary used by `_compute_in_game_open_favorite_metrics`.
    """
    if not events:
        return None
    score_events = [
        event
        for event in events
        if event.get("time_actual_dt") is not None
        and event.get("away_score") is not None
        and event.get("home_score") is not None
    ]
    if not score_events:
        return None
    return min(event["time_actual_dt"] for event in score_events)


def _compute_tipoff_entry_window_price(
    trades_df: pd.DataFrame,
    manifest: dict,
    tipoff_favorite_team: str | None,
    tipoff_time,
    n_trades: int,
) -> tuple[float | None, int]:
    """Size-weighted avg tip-off-favorite-side price of the last N pre-tip trades.

    Returns ``(weighted_price, n_used)`` where ``n_used`` is the actual trade
    count consumed (< N when fewer pre-tip trades exist). Returns ``(None, 0)``
    when the window is empty, N <= 0, or the tip-off favorite is undetermined.
    """
    if (
        n_trades is None
        or n_trades <= 0
        or tipoff_favorite_team is None
        or tipoff_time is None
        or len(manifest.get("token_ids", [])) < 2
        or len(manifest.get("outcomes", [])) < 2
    ):
        return None, 0

    away_token = manifest["token_ids"][0]
    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]
    if tipoff_favorite_team not in (away_team, home_team):
        return None, 0

    pregame = trades_df[trades_df["datetime"] < tipoff_time].sort_values("datetime")
    if pregame.empty:
        return None, 0

    # Transform every trade price to away-team perspective, then to the
    # tip-off favorite's perspective (mirrors the in-game away/home logic).
    away_price = pregame["price"].astype(float).copy()
    home_mask = pregame["asset"] != away_token
    away_price.loc[home_mask] = 1.0 - away_price.loc[home_mask]
    fav_price = away_price if tipoff_favorite_team == away_team else 1.0 - away_price

    window = pregame.assign(_fav_price=fav_price).tail(int(n_trades))
    n_used = int(len(window))
    size = window["size"].astype(float)
    total_size = float(size.sum())
    if total_size <= 0:
        return None, n_used
    weighted = float((window["_fav_price"] * size).sum() / total_size)
    return weighted, n_used


def _attach_favorite_columns(price_path: pd.DataFrame, away_team: str, home_team: str) -> pd.DataFrame:
    path = price_path.copy()
    favorite_teams: list[str] = []
    favorite_prices: list[float] = []
    favorite_margins: list[float] = []
    for row in path.itertuples():
        away_price = float(row.away_price)
        home_price = float(row.home_price)
        if abs(away_price - home_price) <= TIE_TOLERANCE:
            favorite_teams.append("Tie")
            favorite_prices.append(away_price)
        elif away_price > home_price:
            favorite_teams.append(away_team)
            favorite_prices.append(away_price)
        else:
            favorite_teams.append(home_team)
            favorite_prices.append(home_price)
        favorite_margins.append(abs(away_price - home_price))
    path["favorite_team"] = favorite_teams
    path["favorite_price"] = favorite_prices
    path["favorite_margin"] = favorite_margins
    return path


def _build_transition_label(open_band: str | None, tipoff_band: str | None) -> str:
    if not open_band and not tipoff_band:
        return "N/A"
    return f"{open_band or 'N/A'} -> {tipoff_band or 'N/A'}"


def _ordered_group_values(dataset: pd.DataFrame, group_by: str) -> list[str] | None:
    ordering = GROUP_ORDERINGS.get(group_by)
    if not ordering:
        return None
    present = dataset[group_by].dropna().astype(str).unique().tolist()
    return [label for label in ordering if label in present]


def _order_grouped_frame(frame: pd.DataFrame, group_by: str) -> pd.DataFrame | None:
    ordering = GROUP_ORDERINGS.get(group_by)
    if not ordering or group_by not in frame:
        return None
    present = frame[group_by].dropna().astype(str).tolist()
    ordered_labels = [label for label in ordering if label in present]
    if not ordered_labels:
        return None
    ordered = frame.copy()
    ordered[group_by] = pd.Categorical(ordered[group_by], categories=ordered_labels, ordered=True)
    return ordered.sort_values(group_by)


def _favorite_outcome_group(changed_open_to_tipoff: bool, any_switch_pregame: bool | None) -> str:
    if changed_open_to_tipoff:
        return "Open Favorite Reversed by Tip-Off"
    if any_switch_pregame:
        return "Pregame Switched but Reverted"
    return "Stable Favorite"


def _compute_signed_move(open_price: float | None, tipoff_price: float | None) -> float | None:
    if open_price is None or tipoff_price is None or pd.isna(open_price) or pd.isna(tipoff_price):
        return None
    return float(tipoff_price) - float(open_price)


def _prediction_available(favorite_team: str | None, final_winner: str | None) -> bool:
    if not final_winner or not favorite_team or favorite_team == "Tie":
        return False
    return True


def _favorite_won(favorite_team: str | None, final_winner: str | None) -> bool | None:
    if not _prediction_available(favorite_team, final_winner):
        return None
    return bool(favorite_team == final_winner)


def _apply_dark_theme(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111",
        plot_bgcolor="#111",
        legend_title_text="",
        margin={"l": 50, "r": 30, "t": 60, "b": 50},
    )
    return fig


def _safe_mean(series: pd.Series) -> float | None:
    clean = pd.Series(series).dropna()
    if clean.empty:
        return None
    return float(clean.mean())


def _safe_true_count(series: pd.Series) -> int:
    clean = pd.Series(series).fillna(False).astype(bool)
    return int(clean.sum())


def _nullable_bool_rate(series: pd.Series) -> float | None:
    clean = pd.Series(series).dropna()
    if clean.empty:
        return None
    return float(clean.astype(float).mean())


def _safe_share(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return float(count) / float(total)


def _safe_std(series: pd.Series) -> float | None:
    clean = pd.Series(series).dropna()
    if len(clean) < 2:
        return None
    return float(clean.std())


def _safe_rms(series: pd.Series) -> float | None:
    clean = pd.Series(series).dropna()
    if clean.empty:
        return None
    return float((clean.pow(2).mean()) ** 0.5)


def _safe_range(series: pd.Series) -> float | None:
    clean = pd.Series(series).dropna()
    if clean.empty:
        return None
    return float(clean.max() - clean.min())


def _wilson_interval(rate: float | None, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if rate is None or n <= 0:
        return (None, None)
    denominator = 1 + (z**2) / n
    center = (rate + (z**2) / (2 * n)) / denominator
    margin = (
        z
        * sqrt((rate * (1 - rate) / n) + (z**2) / (4 * n**2))
        / denominator
    )
    return (max(0.0, center - margin), min(1.0, center + margin))
