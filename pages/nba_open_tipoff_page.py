"""Dedicated NBA open-vs-tip-off analysis page."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
from dash import Input, Output, dash_table, dcc, html
from dash.dash_table.Format import Format, Group, Scheme

from loaders import get_dates_for_sport
from nba_analysis import AnalysisFilters, GROUPING_OPTIONS
from view_helpers import CARD_STYLE, info_row


BAND_DEFINITIONS = [
    ("Toss-Up", "<0.50 (excluded)"),
    ("Lean Favorite", "0.50-0.53"),
    ("Lower Moderate", "0.53-0.65"),
    ("Upper Moderate", "0.65-0.77"),
    ("Lower Strong", "0.77-0.85"),
    ("Upper Strong", "0.85+"),
]


class NBAOpenTipoffAnalysisPage:
    """Interactive statistical page for NBA open-vs-tip-off analysis."""

    route = "/nba-open-tipoff-analysis"
    title = "NBA Open vs Tip-Off"

    def __init__(self, analysis_service, settings):
        self.analysis_service = analysis_service
        self.settings = settings

    def layout(self):
        settings_dict = self.settings.to_dict()
        return html.Div(
            children=[
                html.H2("NBA Open vs Tip-Off Analysis", style={"marginBottom": "10px"}),
                html.P(
                    "Exploratory page for anchor movement, pregame instability, and favorite swing risk. "
                    "All metrics reuse the same pregame noise gate used by the main charts.",
                    style={"color": "#bbb", "marginTop": 0},
                ),
                html.Div(
                    style={
                        **CARD_STYLE,
                        "marginBottom": "20px",
                        "backgroundColor": "#162033",
                        "border": "1px solid #29415f",
                    },
                    children=[
                        html.H4("Methodology", style={"marginTop": 0, "marginBottom": "8px"}),
                        html.P(
                            "Open is built from a short post-threshold pregame window, not a single trade. "
                            "After cumulative pregame volume clears the threshold, the app uses the configured "
                            "window and anchor statistic to compute per-side prices, then drops games whose "
                            "open favorite never clears the minimum open favorite price.",
                            style={"margin": 0, "color": "#d7e6ff", "fontSize": "13px", "lineHeight": "1.5"},
                        ),
                    ],
                ),
                html.Div(
                    style={"display": "flex", "gap": "20px", "marginBottom": "20px", "flexWrap": "wrap"},
                    children=[
                        html.Div(
                            [
                                html.Label("Price Quality"),
                                dcc.Dropdown(
                                    id="nba-analysis-price-quality",
                                    clearable=False,
                                    options=[
                                        {"label": "All", "value": "all"},
                                        {"label": "Exact", "value": "exact"},
                                        {"label": "Inferred", "value": "inferred"},
                                    ],
                                    value="all",
                                    style={"width": "180px", "color": "#111"},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Label("Start Date"),
                                dcc.Dropdown(
                                    id="nba-analysis-start-date",
                                    clearable=False,
                                    style={"width": "180px", "color": "#111"},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Label("End Date"),
                                dcc.Dropdown(
                                    id="nba-analysis-end-date",
                                    clearable=False,
                                    style={"width": "180px", "color": "#111"},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Label("Group By"),
                                dcc.Dropdown(
                                    id="nba-analysis-group-by",
                                    clearable=False,
                                    options=[{"label": label, "value": key} for key, label in GROUPING_OPTIONS.items()],
                                    value="open_interpretable_band",
                                    style={"width": "260px", "color": "#111"},
                                ),
                            ]
                        ),
                    ],
                ),
                html.Div(
                    style={"display": "flex", "gap": "20px", "marginBottom": "20px", "flexWrap": "wrap"},
                    children=[
                        html.Div(id="nba-analysis-summary", style={**CARD_STYLE, "flex": "1", "minWidth": "320px"}),
                        html.Div(id="nba-analysis-band-card", style={**CARD_STYLE, "flex": "1", "minWidth": "320px"}),
                        html.Div(
                            style={**CARD_STYLE, "flex": "1", "minWidth": "280px", "maxWidth": "320px"},
                            children=[
                                html.H4("Noise Controls", style={"marginTop": 0}),
                                info_row("Open Anchor", settings_dict["open_anchor_stat"].upper()),
                                info_row("Open Anchor Window", f"{settings_dict['open_anchor_window_min']} min"),
                                info_row("Pre-Game Min Cum Vol", f"${settings_dict['pregame_min_cum_vol']:,}"),
                                info_row(
                                    "Min Open Favorite Price",
                                    f"{settings_dict['analysis_min_open_favorite_price']:.2f}",
                                ),
                                info_row("Vol Spike Std Dev", f"{settings_dict['vol_spike_std']}σ"),
                                info_row("Vol Spike Lookback", f"{settings_dict['vol_spike_lookback']} bars"),
                                html.P(
                                    "Open anchor workflow: cross the cumulative pregame volume threshold, take the configured "
                                    "post-threshold window, compute the per-side VWAP or median, then remove games that still "
                                    "do not reach the minimum open favorite price.",
                                    style={"fontSize": "12px", "color": "#999", "marginTop": "10px", "marginBottom": "8px"},
                                ),
                                html.P(
                                    "The dropped-game count in the summary always reflects the active date and price-quality filters.",
                                    style={"fontSize": "12px", "color": "#8fb8e8", "marginTop": 0, "marginBottom": 0},
                                ),
                            ],
                        ),
                    ],
                ),
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(420px, 1fr))", "gap": "20px"},
                    children=[
                        dcc.Loading(dcc.Graph(id="nba-analysis-transition-heatmap", style={"height": "420px"})),
                        dcc.Loading(dcc.Graph(id="nba-analysis-signed-move", style={"height": "420px"})),
                        dcc.Loading(dcc.Graph(id="nba-analysis-swing-rate", style={"height": "420px"})),
                        dcc.Loading(dcc.Graph(id="nba-analysis-volatility", style={"height": "420px"})),
                    ],
                ),
                html.Div(style={"marginTop": "20px"}, children=[dcc.Loading(dcc.Graph(id="nba-analysis-open-vs-tipoff", style={"height": "520px"}))]),
                html.Div(
                    style={"marginTop": "20px"},
                    children=[
                        html.H3("Grouped Summary", style={"marginBottom": "10px"}),
                        dash_table.DataTable(
                            id="nba-analysis-table",
                            page_size=12,
                            sort_action="native",
                            style_table={"overflowX": "auto"},
                            style_cell={
                                "backgroundColor": "#141422",
                                "color": "#eee",
                                "border": "1px solid #333",
                                "padding": "8px",
                                "textAlign": "left",
                                "fontFamily": "system-ui, sans-serif",
                            },
                            style_header={
                                "backgroundColor": "#1f1f33",
                                "fontWeight": "bold",
                                "border": "1px solid #333",
                            },
                        ),
                    ],
                ),
            ]
        )

    def register_callbacks(self, app):
        @app.callback(
            Output("nba-analysis-start-date", "options"),
            Output("nba-analysis-start-date", "value"),
            Output("nba-analysis-end-date", "options"),
            Output("nba-analysis-end-date", "value"),
            Input("nba-analysis-price-quality", "value"),
        )
        def populate_dates(price_quality):
            dates = get_dates_for_sport(self.analysis_service.data_dir, "nba")
            options = [{"label": date, "value": date} for date in dates]
            start, end = _default_date_window(dates)
            return options, start, options, end

        @app.callback(
            Output("nba-analysis-summary", "children"),
            Output("nba-analysis-band-card", "children"),
            Output("nba-analysis-transition-heatmap", "figure"),
            Output("nba-analysis-signed-move", "figure"),
            Output("nba-analysis-swing-rate", "figure"),
            Output("nba-analysis-open-vs-tipoff", "figure"),
            Output("nba-analysis-volatility", "figure"),
            Output("nba-analysis-table", "data"),
            Output("nba-analysis-table", "columns"),
            Input("nba-analysis-price-quality", "value"),
            Input("nba-analysis-start-date", "value"),
            Input("nba-analysis-end-date", "value"),
            Input("nba-analysis-group-by", "value"),
        )
        def update_analysis(price_quality, start_date, end_date, group_by):
            prepared = self.analysis_service.prepare_dataset(
                AnalysisFilters(
                    price_quality=price_quality or "all",
                    start_date=start_date,
                    end_date=end_date,
                )
            )
            dataset = prepared.dataset
            summary = self.analysis_service.build_summary(
                dataset,
                dropped_open_filter_games=prepared.dropped_open_filter_games,
            )
            figures = self.analysis_service.figure_builder().build_figures(dataset, group_by)
            table = self.analysis_service.build_group_summary(dataset, group_by)

            summary_children = [
                html.H4("Analysis Summary", style={"marginTop": 0}),
                info_row("NBA Games", f"{summary.games:,}"),
                info_row("Dropped by Open Filter", f"{summary.dropped_open_filter_games:,}"),
                html.P(
                    "Dropped games are ultra-tight or incomplete opens that fail the minimum open favorite price filter after the "
                    "post-threshold anchor window is computed.",
                    style={"fontSize": "12px", "color": "#8fb8e8", "marginTop": "10px", "marginBottom": "10px"},
                ),
                info_row(
                    "Open -> Tip-Off Swing Rate",
                    _format_pct(summary.open_to_tipoff_swing_rate),
                ),
                info_row(
                    "Any Durable Pregame Switch Rate",
                    _format_pct(summary.any_pregame_switch_rate),
                ),
                info_row("Mean Absolute Move", _format_number(summary.mean_abs_move)),
                info_row("Mean Realized Volatility", _format_number(summary.mean_path_volatility)),
            ]

            band_counts = dataset["open_interpretable_band"].value_counts()
            band_children = [
                html.H4("Band Reference", style={"marginTop": 0}),
                html.P(
                    "Open-band definitions used in the active analysis, with game counts after the current filters. Toss-Up games are excluded by the minimum open favorite price rule.",
                    style={"fontSize": "12px", "color": "#bbb", "marginTop": 0, "marginBottom": "10px"},
                ),
            ]
            for label, band_range in BAND_DEFINITIONS:
                count = (
                    prepared.dropped_open_filter_games
                    if label == "Toss-Up"
                    else int(band_counts.get(label, 0))
                )
                band_children.append(info_row(f"{label} ({band_range})", f"{count:,}"))

            columns = _build_table_columns(table)
            return (
                summary_children,
                band_children,
                figures["transition_heatmap"],
                figures["signed_move"],
                figures["swing_rates"],
                figures["open_vs_tipoff"],
                figures["volatility"],
                table.to_dict("records"),
                columns,
            )


def _format_pct(value):
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def _format_number(value):
    if value is None:
        return "N/A"
    return f"{value:.4f}"


def _build_table_columns(table: pd.DataFrame) -> list[dict]:
    percent_columns = {
        "open_to_tipoff_swing_rate",
        "any_pregame_switch_rate",
        "games_share",
        "open_to_tipoff_swing_ci_low",
        "open_to_tipoff_swing_ci_high",
    }
    columns: list[dict] = []
    for column in table.columns:
        definition = {"name": column.replace("_", " ").title(), "id": column}
        if column in percent_columns:
            definition["type"] = "numeric"
            definition["format"] = Format(precision=2, scheme=Scheme.percentage)
        elif column == "games":
            definition["type"] = "numeric"
            definition["format"] = Format(group=Group.yes, precision=0, scheme=Scheme.fixed)
        elif pd.api.types.is_numeric_dtype(table[column]):
            definition["type"] = "numeric"
            definition["format"] = Format(precision=4, scheme=Scheme.fixed)
        columns.append(definition)
    return columns


def _default_date_window(dates: list[str]) -> tuple[str | None, str | None]:
    if not dates:
        return None, None

    parsed = pd.to_datetime(dates)
    end = parsed.max()
    target_start = end - timedelta(days=30)

    eligible = parsed[parsed >= target_start]
    start = eligible.min() if len(eligible) else parsed.min()

    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
