"""Backtest results browser page."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from dash import Input, Output, State, callback_context, dcc, html, no_update
from dash.dash_table import DataTable
from dash.dash_table.Format import Format, Scheme

from view_helpers import CARD_STYLE

RESULTS_DIR = Path("backtest_results")

# Columns to display and their formatting
DISPLAY_COLUMNS = [
    {"id": "match_id", "name": "Match", "type": "text"},
    {"id": "date", "name": "Date", "type": "text"},
    {"id": "sport", "name": "Sport", "type": "text"},
    {"id": "dip_threshold", "name": "Dip (c)", "type": "numeric"},
    {"id": "dip_anchor", "name": "Anchor", "type": "text"},
    {"id": "exit_type", "name": "Exit", "type": "text"},
    {"id": "fee_model", "name": "Fee", "type": "text"},
    {"id": "entry_price", "name": "Entry", "type": "numeric",
     "format": Format(precision=4, scheme=Scheme.fixed)},
    {"id": "entry_time", "name": "Entry Time", "type": "text"},
    {"id": "exit_price", "name": "Exit Price", "type": "numeric",
     "format": Format(precision=4, scheme=Scheme.fixed)},
    {"id": "roi_pct", "name": "ROI", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.percentage)},
    {"id": "net_pnl_cents", "name": "Net PnL (c)", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"id": "true_pnl_cents", "name": "True PnL (c)", "type": "numeric",
     "format": Format(precision=2, scheme=Scheme.fixed)},
    {"id": "max_drawdown_cents", "name": "Max DD (c)", "type": "numeric",
     "format": Format(precision=1, scheme=Scheme.fixed)},
    {"id": "hold_seconds", "name": "Hold (s)", "type": "numeric"},
    {"id": "settlement_method", "name": "Settlement", "type": "text"},
    {"id": "status", "name": "Status", "type": "text"},
]


def _get_available_runs() -> list[str]:
    if not RESULTS_DIR.exists():
        return []
    runs = sorted(
        [d.name for d in RESULTS_DIR.iterdir() if d.is_dir() and (d / "results_per_game.csv").exists()],
        reverse=True,
    )
    return runs


def _load_run(run_name: str) -> pd.DataFrame:
    path = RESULTS_DIR / run_name / "results_per_game.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _coerce_persisted_filter_value(current_value, valid_values, fallback):
    """Keep a persisted selection only when it still exists for the chosen run."""
    if current_value in valid_values:
        return current_value
    return fallback


def _default_filter_state() -> dict:
    return {
        "run": None,
        "exit": "all",
        "fee": "all",
        "anchor": "all",
        "dip": "all",
        "status": "filled",
        "outcome": ["winners", "losers"],
    }


class BacktestResultsPage:
    """Browse backtest results and click through to main dashboard."""

    route = "/backtest-results"
    title = "Backtest Results"

    def __init__(self):
        pass

    def layout(self):
        runs = _get_available_runs()
        run_options = [{"label": r, "value": r} for r in runs]
        default_run = runs[0] if runs else None

        return html.Div(children=[
            dcc.Store(id="bt-filter-store", storage_type="local"),
            html.H2("Backtest Results", style={"marginBottom": "10px"}),

            # Run selector and filters
            html.Div(
                style={"display": "flex", "gap": "20px", "marginBottom": "20px", "flexWrap": "wrap"},
                children=[
                    html.Div([
                        html.Label("Run"),
                        dcc.Dropdown(
                            id="bt-run-picker",
                            options=run_options,
                            value=default_run,
                            clearable=False,
                            persistence=True,
                            persistence_type="local",
                            style={"width": "220px", "color": "#111"},
                        ),
                    ]),
                    html.Div([
                        html.Label("Exit Type"),
                        dcc.Dropdown(
                            id="bt-exit-filter",
                            clearable=False,
                            persistence=True,
                            persistence_type="local",
                            style={"width": "200px", "color": "#111"},
                        ),
                    ]),
                    html.Div([
                        html.Label("Fee Model"),
                        dcc.Dropdown(
                            id="bt-fee-filter",
                            clearable=False,
                            persistence=True,
                            persistence_type="local",
                            style={"width": "160px", "color": "#111"},
                        ),
                    ]),
                    html.Div([
                        html.Label("Dip Anchor"),
                        dcc.Dropdown(
                            id="bt-anchor-filter",
                            clearable=False,
                            persistence=True,
                            persistence_type="local",
                            style={"width": "160px", "color": "#111"},
                        ),
                    ]),
                    html.Div([
                        html.Label("Dip Threshold"),
                        dcc.Dropdown(
                            id="bt-dip-filter",
                            clearable=False,
                            persistence=True,
                            persistence_type="local",
                            style={"width": "160px", "color": "#111"},
                        ),
                    ]),
                    html.Div([
                        html.Label("Status"),
                        dcc.Dropdown(
                            id="bt-status-filter",
                            options=[
                                {"label": "All", "value": "all"},
                                {"label": "Filled", "value": "filled"},
                                {"label": "Not Triggered", "value": "not_triggered"},
                            ],
                            value="filled",
                            clearable=False,
                            persistence=True,
                            persistence_type="local",
                            style={"width": "160px", "color": "#111"},
                        ),
                    ]),
                    html.Div([
                        html.Label("Outcome"),
                        dcc.Checklist(
                            id="bt-outcome-filter",
                            options=[
                                {"label": " Winners", "value": "winners"},
                                {"label": " Losers", "value": "losers"},
                            ],
                            value=["winners", "losers"],
                            inline=False,
                            persistence=True,
                            persistence_type="local",
                            style={"paddingTop": "4px"},
                            labelStyle={"display": "block", "color": "#e2e8f0", "fontSize": "13px", "lineHeight": "1.8", "cursor": "pointer"},
                        ),
                    ]),
                ],
            ),

            # Summary stats card
            html.Div(id="bt-summary-card", style={
                **CARD_STYLE, "marginBottom": "20px",
            }),

            # Results table
            html.Div([
                html.P(
                    "Click any row to view that game in the main dashboard.",
                    style={"color": "#888", "marginBottom": "8px", "fontSize": "13px"},
                ),
                DataTable(
                    id="bt-results-table",
                    columns=[
                        {**col, "format": col["format"]} if "format" in col
                        else col
                        for col in DISPLAY_COLUMNS
                    ],
                    data=[],
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
                        "fontSize": "13px",
                        "textAlign": "left",
                    },
                    style_data_conditional=[
                        {
                            "if": {"filter_query": "{status} = filled AND {roi_pct} > 0"},
                            "backgroundColor": "#0a2e0a",
                        },
                        {
                            "if": {"filter_query": "{status} = filled AND {roi_pct} < 0"},
                            "backgroundColor": "#2e0a0a",
                        },
                        {
                            "if": {"filter_query": "{status} = not_triggered"},
                            "color": "#666",
                        },
                        {
                            "if": {"state": "active"},
                            "backgroundColor": "#1a3a5c",
                            "border": "1px solid #9ad1ff",
                        },
                    ],
                    page_size=50,
                ),
            ]),
        ])

    def register_callbacks(self, app):

        @app.callback(
            Output("bt-run-picker", "value"),
            Output("bt-status-filter", "value"),
            Output("bt-outcome-filter", "value"),
            Input("url", "pathname"),
            State("bt-filter-store", "data"),
        )
        def restore_saved_filters(pathname, stored_filters):
            if pathname != self.route:
                return no_update, no_update, no_update

            saved = _default_filter_state()
            if stored_filters:
                saved.update(stored_filters)

            available_runs = _get_available_runs()
            default_run = available_runs[0] if available_runs else None
            run_value = saved["run"] if saved["run"] in available_runs else default_run

            return (
                run_value,
                saved.get("status", "filled"),
                saved.get("outcome", ["winners", "losers"]),
            )

        @app.callback(
            Output("bt-exit-filter", "options"),
            Output("bt-exit-filter", "value"),
            Output("bt-fee-filter", "options"),
            Output("bt-fee-filter", "value"),
            Output("bt-anchor-filter", "options"),
            Output("bt-anchor-filter", "value"),
            Output("bt-dip-filter", "options"),
            Output("bt-dip-filter", "value"),
            Input("bt-run-picker", "value"),
            State("bt-filter-store", "data"),
        )
        def populate_filters(run_name, stored_filters):
            if not run_name:
                return [], None, [], None, [], None, [], None
            df = _load_run(run_name)
            if df.empty:
                return [], None, [], None, [], None, [], None

            saved = _default_filter_state()
            if stored_filters:
                saved.update(stored_filters)

            exit_types = sorted(df["exit_type"].dropna().unique())
            exit_opts = [{"label": "All", "value": "all"}] + [
                {"label": e, "value": e} for e in exit_types
            ]

            fee_models = sorted(df["fee_model"].dropna().unique())
            fee_opts = [{"label": "All", "value": "all"}] + [
                {"label": f, "value": f} for f in fee_models
            ]

            anchor_opts = [{"label": "All", "value": "all"}]
            if "dip_anchor" in df.columns:
                anchors = sorted(df["dip_anchor"].dropna().unique())
                anchor_opts += [{"label": a, "value": a} for a in anchors]

            dip_thresholds = sorted(df["dip_threshold"].dropna().unique())
            dip_opts = [{"label": "All", "value": "all"}] + [
                {"label": f"{int(d)}c", "value": str(d)} for d in dip_thresholds
            ]

            exit_values = {opt["value"] for opt in exit_opts}
            fee_values = {opt["value"] for opt in fee_opts}
            anchor_values = {opt["value"] for opt in anchor_opts}
            dip_values = {opt["value"] for opt in dip_opts}

            return (
                exit_opts,
                _coerce_persisted_filter_value(saved.get("exit"), exit_values, "all"),
                fee_opts,
                _coerce_persisted_filter_value(saved.get("fee"), fee_values, "all"),
                anchor_opts,
                _coerce_persisted_filter_value(saved.get("anchor"), anchor_values, "all"),
                dip_opts,
                _coerce_persisted_filter_value(saved.get("dip"), dip_values, "all"),
            )

        @app.callback(
            Output("bt-filter-store", "data"),
            Input("bt-run-picker", "value"),
            Input("bt-exit-filter", "value"),
            Input("bt-fee-filter", "value"),
            Input("bt-anchor-filter", "value"),
            Input("bt-dip-filter", "value"),
            Input("bt-status-filter", "value"),
            Input("bt-outcome-filter", "value"),
            prevent_initial_call=True,
        )
        def persist_filters(run_name, exit_filter, fee_filter, anchor_filter, dip_filter, status_filter, outcome_filter):
            return {
                "run": run_name,
                "exit": exit_filter or "all",
                "fee": fee_filter or "all",
                "anchor": anchor_filter or "all",
                "dip": dip_filter or "all",
                "status": status_filter or "filled",
                "outcome": outcome_filter or ["winners", "losers"],
            }

        @app.callback(
            Output("bt-results-table", "data"),
            Output("bt-summary-card", "children"),
            Input("bt-run-picker", "value"),
            Input("bt-exit-filter", "value"),
            Input("bt-fee-filter", "value"),
            Input("bt-anchor-filter", "value"),
            Input("bt-dip-filter", "value"),
            Input("bt-status-filter", "value"),
            Input("bt-outcome-filter", "value"),
        )
        def update_table(run_name, exit_filter, fee_filter, anchor_filter, dip_filter, status_filter, outcome_filter):
            if not run_name:
                return [], "No run selected"
            df = _load_run(run_name)
            if df.empty:
                return [], "No data"

            # Apply filters
            if exit_filter and exit_filter != "all":
                df = df[df["exit_type"] == exit_filter]
            if fee_filter and fee_filter != "all":
                df = df[df["fee_model"] == fee_filter]
            if anchor_filter and anchor_filter != "all" and "dip_anchor" in df.columns:
                df = df[df["dip_anchor"] == anchor_filter]
            if dip_filter and dip_filter != "all":
                df = df[df["dip_threshold"] == float(dip_filter)]
            if status_filter and status_filter != "all":
                df = df[df["status"] == status_filter]

            # Outcome filter: only applies to filled rows; non-filled pass through
            outcome_filter = outcome_filter or []
            show_winners = "winners" in outcome_filter
            show_losers = "losers" in outcome_filter
            if not (show_winners and show_losers) and "roi_pct" in df.columns:
                filled_mask = df["status"] == "filled"
                winner_mask = df["roi_pct"] > 0
                keep_mask = ~filled_mask  # non-filled always pass through
                if show_winners:
                    keep_mask |= filled_mask & winner_mask
                if show_losers:
                    keep_mask |= filled_mask & ~winner_mask
                df = df[keep_mask]

            # Build summary
            filled = df[df["status"] == "filled"]
            n_total = len(df)
            n_filled = len(filled)
            summary_items = [
                html.Span(f"Showing {n_total} rows", style={"marginRight": "30px"}),
                html.Span(f"Filled: {n_filled}", style={"marginRight": "30px"}),
            ]
            if n_filled > 0:
                mean_roi = filled["roi_pct"].mean()
                wins = (filled["roi_pct"] > 0).sum()
                losses = (filled["roi_pct"] < 0).sum()
                mean_entry = filled["entry_price"].mean()
                summary_items.extend([
                    html.Span(f"Mean ROI: {mean_roi:.2%}", style={"marginRight": "30px"}),
                    html.Span(f"W/L: {wins}/{losses}", style={"marginRight": "30px"}),
                    html.Span(f"Avg Entry: {mean_entry:.3f}", style={"marginRight": "30px"}),
                ])
                if "max_drawdown_cents" in filled.columns:
                    mean_dd = filled["max_drawdown_cents"].mean()
                    summary_items.append(
                        html.Span(f"Avg Max DD: {mean_dd:.1f}c", style={"marginRight": "30px"}),
                    )

            summary = html.Div(
                style={"display": "flex", "flexWrap": "wrap", "gap": "4px"},
                children=summary_items,
            )

            # Prepare table data
            display_cols = [c["id"] for c in DISPLAY_COLUMNS]
            available = [c for c in display_cols if c in df.columns]
            table_df = df[available].copy()
            records = table_df.to_dict("records")

            return records, summary

        @app.callback(
            Output("url", "href", allow_duplicate=True),
            Input("bt-results-table", "active_cell"),
            State("bt-results-table", "derived_virtual_data"),
            prevent_initial_call=True,
        )
        def navigate_to_game(active_cell, virtual_data):
            if not active_cell or not virtual_data:
                return no_update
            row = virtual_data[active_cell["row"]]
            match_id = row.get("match_id")
            date = row.get("date")
            sport = row.get("sport")
            if not match_id or not date:
                return no_update
            # Navigate to main dashboard with query params (atomic href change)
            return f"/?bt_game={date}|{match_id}&bt_sport={sport or 'nba'}&bt_date={date}"
