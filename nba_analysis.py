"""Reusable NBA open-vs-tip-off analysis services and figures."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import sqrt
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from analytics import (
    ACTIVE_INTERPRETABLE_BAND_LABELS,
    INTERPRETABLE_BAND_LABELS,
    TIE_TOLERANCE,
    build_game_analytics_dataset,
    get_analytics_view,
)
from loaders import load_game
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
    open_to_tipoff_swing_rate: float | None
    any_pregame_switch_rate: float | None
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

    def __init__(self, data_dir: str = "data", settings: ChartSettings | None = None):
        self.data_dir = str(Path(data_dir))
        self.settings = settings or ChartSettings()
        self.path_analyzer = PregameFavoritePathAnalyzer(self.settings)

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
            return NBAOpenTipoffSummary(0, dropped_open_filter_games, None, None, None, None)

        return NBAOpenTipoffSummary(
            games=len(dataset),
            dropped_open_filter_games=dropped_open_filter_games,
            open_to_tipoff_swing_rate=_safe_mean(dataset["favorite_changed_open_to_tipoff"].astype(float)),
            any_pregame_switch_rate=_safe_mean(dataset["any_favorite_switch_pregame"].astype(float)),
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
            open_to_tipoff_swing_rate=("favorite_changed_open_to_tipoff", lambda s: float(pd.Series(s).mean())),
            any_pregame_switch_rate=("any_favorite_switch_pregame", lambda s: float(pd.Series(s).mean())),
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

    if progress_observer is None:
        base = get_analytics_view(
            data_dir=data_dir,
            sport="nba",
            price_quality_filter="all",
            pregame_min_cum_vol=pregame_min_cum_vol,
            open_anchor_stat=open_anchor_stat,
            open_anchor_window_min=open_anchor_window_min,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        base_records = build_game_analytics_dataset(
            data_dir=data_dir,
            pregame_min_cum_vol=pregame_min_cum_vol,
            open_anchor_stat=open_anchor_stat,
            open_anchor_window_min=open_anchor_window_min,
            start_date=start_date,
            end_date=end_date,
            progress_observer=progress_observer.child("base"),
        )
        if base_records.empty:
            return base_records
        base = base_records[base_records["sport"] == "nba"].copy()
        quantiles = _compute_quantiles_for_progress_build(base)
        for anchor in ("open", "tipoff"):
            price_col = f"{anchor}_favorite_price"
            band_col = f"{anchor}_quantile_band"
            base[band_col] = base.apply(
                lambda row: _assign_quantile_band_for_progress_build(
                    row.get(price_col),
                    quantiles.get(anchor),
                ),
                axis=1,
            )
    if base.empty:
        return base

    rows: list[dict[str, Any]] = []
    records = base.to_dict("records")
    if progress_observer is not None:
        progress_observer.start(total=len(records), description="Processing NBA detailed metrics")

    for index, row in enumerate(records, start=1):
        details = _load_nba_detail_row(
            data_dir,
            row["date"],
            row["match_id"],
            pregame_min_cum_vol,
            vol_spike_std,
            vol_spike_lookback,
        )
        merged = {**row, **details}
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
        merged["interpretable_transition"] = _build_transition_label(
            merged.get("open_interpretable_band"),
            merged.get("tipoff_interpretable_band"),
        )
        merged["quantile_transition"] = _build_transition_label(
            merged.get("open_quantile_band"),
            merged.get("tipoff_quantile_band"),
        )
        merged["favorite_outcome_group"] = _favorite_outcome_group(
            merged["favorite_changed_open_to_tipoff"],
            merged.get("any_favorite_switch_pregame"),
        )
        rows.append(merged)
        if progress_observer is not None:
            progress_observer.advance(index=index, match_id=row["match_id"], date=row["date"])

    dataset = pd.DataFrame(rows)
    dataset["date"] = pd.to_datetime(dataset["date"]).dt.strftime("%Y-%m-%d")
    if progress_observer is not None:
        progress_observer.finish(total=len(records))
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


@lru_cache(maxsize=256)
def _load_nba_detail_row(
    data_dir: str,
    date: str,
    match_id: str,
    pregame_min_cum_vol: float,
    vol_spike_std: float,
    vol_spike_lookback: int,
) -> dict[str, Any]:
    settings = ChartSettings(
        pregame_min_cum_vol=pregame_min_cum_vol,
        vol_spike_std=vol_spike_std,
        vol_spike_lookback=vol_spike_lookback,
    )
    path_analyzer = PregameFavoritePathAnalyzer(settings)
    game = load_game(data_dir, date, match_id)
    return path_analyzer.compute_metrics(game["trades_df"], game["events"])


def _favorite_changed(open_team: str | None, tipoff_team: str | None) -> bool:
    if not open_team or not tipoff_team:
        return False
    return open_team != tipoff_team


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
