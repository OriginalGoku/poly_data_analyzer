"""Scenario results browser page — per-position + aggregation + heatmap."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dcc, html, no_update
from dash.dash_table import DataTable

from view_helpers import CARD_STYLE

RESULTS_DIR = Path("backtest_results")

POSITIONS_FILE = "results_positions.csv"
AGGREGATION_FILE = "results_aggregation.csv"


def _get_available_runs() -> list[str]:
    if not RESULTS_DIR.exists():
        return []
    runs = []
    for d in RESULTS_DIR.iterdir():
        if d.is_dir() and (d / POSITIONS_FILE).exists():
            runs.append(d.name)
    return sorted(runs, reverse=True)


def _load(run_name: str, filename: str) -> pd.DataFrame:
    path = RESULTS_DIR / run_name / filename
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _heatmap_figure(agg_df: pd.DataFrame, metric: str = "mean_roi_pct") -> go.Figure | None:
    if agg_df.empty or metric not in agg_df.columns:
        return None
    sweep_cols = [c for c in agg_df.columns if c.startswith("sweep_axis_")]
    if not sweep_cols:
        return None

    if len(sweep_cols) >= 2:
        row_dim, col_dim = sweep_cols[0], sweep_cols[1]
        try:
            pivoted = agg_df.pivot_table(
                index=row_dim, columns=col_dim, values=metric, aggfunc="mean"
            )
        except Exception:
            return None
        fig = go.Figure(
            data=go.Heatmap(
                z=pivoted.values,
                x=list(pivoted.columns),
                y=list(pivoted.index),
                colorscale="RdYlGn",
                colorbar=dict(title=metric),
            )
        )
        fig.update_layout(
            title=f"{metric} ({row_dim} x {col_dim})",
            xaxis_title=col_dim,
            yaxis_title=row_dim,
            template="plotly_dark",
        )
        return fig

    dim = sweep_cols[0]
    grouped = agg_df.groupby(dim, dropna=False)[metric].mean().reset_index()
    fig = go.Figure(
        data=go.Bar(x=grouped[dim].astype(str), y=grouped[metric])
    )
    fig.update_layout(
        title=f"{metric} by {dim}",
        xaxis_title=dim,
        yaxis_title=metric,
        template="plotly_dark",
    )
    return fig


def _data_table(table_id: str, df: pd.DataFrame) -> DataTable:
    columns = [{"name": c, "id": c} for c in df.columns]
    return DataTable(
        id=table_id,
        columns=columns,
        data=df.to_dict("records"),
        sort_action="native",
        sort_mode="multi",
        style_table={"overflowX": "auto"},
        style_header={
            "backgroundColor": "#1a1a2e",
            "color": "#9ad1ff",
            "fontWeight": "bold",
            "border": "1px solid #333",
        },
        style_cell={
            "backgroundColor": "#111",
            "color": "#eee",
            "border": "1px solid #333",
            "padding": "6px 10px",
            "fontSize": "12px",
            "textAlign": "left",
            "maxWidth": "260px",
            "overflow": "hidden",
            "textOverflow": "ellipsis",
        },
        page_size=25,
    )


class ScenarioResultsPage:
    """Browse per-position and aggregation outputs from the scenario runner."""

    route = "/scenario-results"
    title = "Scenario Results"

    def __init__(self):
        pass

    def layout(self):
        runs = _get_available_runs()
        run_options = [{"label": r, "value": r} for r in runs]
        default_run = runs[0] if runs else None

        return html.Div(children=[
            html.H2("Scenario Results", style={"marginBottom": "10px"}),
            html.Div(
                style={"display": "flex", "gap": "20px", "marginBottom": "20px", "flexWrap": "wrap"},
                children=[
                    html.Div([
                        html.Label("Run"),
                        dcc.Dropdown(
                            id="scen-results-run",
                            options=run_options,
                            value=default_run,
                            clearable=False,
                            style={"width": "360px", "color": "#111"},
                        ),
                    ]),
                ],
            ),
            html.Div(id="scen-results-summary", style={**CARD_STYLE, "marginBottom": "16px"}),

            html.H3("Aggregation"),
            html.Div(id="scen-results-agg", style={"marginBottom": "20px"}),

            html.H3("Sweep Heatmap"),
            html.Div(
                id="scen-results-heatmap-wrap",
                style={"marginBottom": "20px"},
                children=dcc.Graph(id="scen-results-heatmap"),
            ),

            html.H3("Per-Position Rows"),
            html.Div(id="scen-results-positions"),
        ])

    def register_callbacks(self, app):

        @app.callback(
            Output("scen-results-summary", "children"),
            Output("scen-results-agg", "children"),
            Output("scen-results-heatmap", "figure"),
            Output("scen-results-positions", "children"),
            Input("scen-results-run", "value"),
        )
        def update_run(run_name):
            if not run_name:
                empty_fig = go.Figure().update_layout(template="plotly_dark")
                return "No run selected.", "", empty_fig, ""

            positions = _load(run_name, POSITIONS_FILE)
            aggregation = _load(run_name, AGGREGATION_FILE)

            n_pos = len(positions)
            n_scen = aggregation["scenario_name"].nunique() if not aggregation.empty else 0
            sweep_cols = [c for c in aggregation.columns if c.startswith("sweep_axis_")]

            summary_children = html.Div(
                style={"display": "flex", "flexWrap": "wrap", "gap": "24px"},
                children=[
                    html.Span(f"Run: {run_name}", style={"fontWeight": "bold"}),
                    html.Span(f"Positions: {n_pos}"),
                    html.Span(f"Scenarios (with sweeps): {n_scen}"),
                    html.Span(f"Sweep axes: {', '.join(sweep_cols) if sweep_cols else 'none'}"),
                ],
            )

            agg_table = _data_table("scen-results-agg-table", aggregation) if not aggregation.empty else html.Div("No aggregation data.")
            positions_table = _data_table("scen-results-positions-table", positions) if not positions.empty else html.Div("No position rows.")

            fig = _heatmap_figure(aggregation)
            if fig is None:
                fig = go.Figure().update_layout(
                    template="plotly_dark",
                    title="No sweep axes — heatmap unavailable",
                )

            return summary_children, agg_table, fig, positions_table
