"""Backtest runner page — configure and execute backtests from the UI."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
from dash import Input, Output, State, dcc, html, no_update

from loaders import get_available_sports_from_manifests, get_dates_for_sport
from settings import load_chart_settings
from view_helpers import CARD_STYLE

logger = logging.getLogger(__name__)

DATA_DIR = "data"
RESULTS_DIR = Path("backtest_results")
SETTINGS_PATH = Path(__file__).parents[1] / "chart_settings.json"

EXIT_TYPE_OPTIONS = [
    {"label": "Settlement", "value": "settlement"},
    {"label": "Reversion to Open", "value": "reversion_to_open"},
    {"label": "Reversion to Partial", "value": "reversion_to_partial"},
    {"label": "Fixed Profit", "value": "fixed_profit"},
]

DIP_THRESHOLD_OPTIONS = [
    {"label": f"{t}c", "value": t}
    for t in [5, 10, 15, 20, 25, 30, 40, 50]
]

FEE_MODEL_OPTIONS = [
    {"label": "Taker (0.2%)", "value": "taker"},
    {"label": "Maker (0%)", "value": "maker"},
]

DIP_ANCHOR_OPTIONS = [
    {"label": "Open", "value": "open"},
    {"label": "Tip-Off", "value": "tipoff"},
]

# Shared state for run progress
_run_state = {
    "running": False,
    "output_dir": None,
    "error": None,
    "progress_msg": "",
    "games_done": 0,
    "games_total": 0,
}


class BacktestRunnerPage:
    """Configure and run backtests from the dashboard."""

    route = "/run-backtest"
    title = "Run Backtest"

    def __init__(self):
        pass

    def layout(self):
        sports = get_available_sports_from_manifests(DATA_DIR)
        sport_options = [{"label": s.upper(), "value": s} for s in sports]
        default_sport = "nba" if "nba" in sports else (sports[0] if sports else None)

        dates = get_dates_for_sport(DATA_DIR, default_sport) if default_sport else []
        date_options = [{"label": d, "value": d} for d in dates]

        # Load outlier filter settings for display
        chart_settings = load_chart_settings(SETTINGS_PATH).to_dict()
        bw = chart_settings.get("outlier_backward_window", 20)
        fw = chart_settings.get("outlier_forward_window", 20)
        bt = chart_settings.get("outlier_backward_threshold", 0.75)
        ft = chart_settings.get("outlier_forward_threshold", 0.50)
        skip_s = chart_settings.get("outlier_forward_skip_seconds", 10)

        return html.Div(children=[
            html.H2("Run Backtest", style={"marginBottom": "10px"}),

            # Flash-crash filter info
            html.Div(
                style={
                    **CARD_STYLE,
                    "marginBottom": "16px",
                    "padding": "10px 16px",
                    "fontSize": "13px",
                    "display": "flex",
                    "gap": "24px",
                    "flexWrap": "wrap",
                    "alignItems": "center",
                },
                children=[
                    html.Span("Flash-Crash Filter", style={"fontWeight": "bold", "color": "#93c5fd"}),
                    html.Span(f"Backward Window: {bw} trades"),
                    html.Span(f"Forward Window: {fw} trades"),
                    html.Span(f"Backward Threshold: {bt:.0%}"),
                    html.Span(f"Forward Threshold: {ft:.0%}"),
                    html.Span(f"Forward Skip: {skip_s}s"),
                ],
            ),

            # Parameter grid
            html.Div(
                style={"display": "flex", "gap": "20px", "marginBottom": "20px", "flexWrap": "wrap"},
                children=[
                    # Sport
                    html.Div([
                        html.Label("Sport"),
                        dcc.Dropdown(
                            id="run-sport",
                            options=sport_options,
                            value=default_sport,
                            clearable=False,
                            style={"width": "140px", "color": "#111"},
                        ),
                    ]),
                    # Start date
                    html.Div([
                        html.Label("Start Date"),
                        dcc.Dropdown(
                            id="run-start-date",
                            options=date_options,
                            value=date_options[-1]["value"] if date_options else None,
                            clearable=False,
                            style={"width": "180px", "color": "#111"},
                        ),
                    ]),
                    # End date
                    html.Div([
                        html.Label("End Date"),
                        dcc.Dropdown(
                            id="run-end-date",
                            options=date_options,
                            value=date_options[0]["value"] if date_options else None,
                            clearable=False,
                            style={"width": "180px", "color": "#111"},
                        ),
                    ]),
                ],
            ),

            html.Div(
                style={"display": "flex", "gap": "20px", "marginBottom": "20px", "flexWrap": "wrap"},
                children=[
                    # Dip thresholds
                    html.Div([
                        html.Label("Dip Thresholds"),
                        dcc.Dropdown(
                            id="run-dip-thresholds",
                            options=DIP_THRESHOLD_OPTIONS,
                            value=[10, 15, 30],
                            multi=True,
                            style={"width": "280px", "color": "#111"},
                        ),
                    ]),
                    # Dip anchors
                    html.Div([
                        html.Label("Dip Anchors"),
                        dcc.Dropdown(
                            id="run-dip-anchors",
                            options=DIP_ANCHOR_OPTIONS,
                            value=["open"],
                            multi=True,
                            style={"width": "220px", "color": "#111"},
                        ),
                    ]),
                    # Exit types
                    html.Div([
                        html.Label("Exit Types"),
                        dcc.Dropdown(
                            id="run-exit-types",
                            options=EXIT_TYPE_OPTIONS,
                            value=["settlement", "reversion_to_open"],
                            multi=True,
                            style={"width": "320px", "color": "#111"},
                        ),
                    ]),
                    # Fee models
                    html.Div([
                        html.Label("Fee Models"),
                        dcc.Dropdown(
                            id="run-fee-models",
                            options=FEE_MODEL_OPTIONS,
                            value=["taker"],
                            multi=True,
                            style={"width": "240px", "color": "#111"},
                        ),
                    ]),
                ],
            ),

            # Output folder name
            html.Div(
                style={"display": "flex", "gap": "12px", "alignItems": "flex-end", "marginBottom": "20px"},
                children=[
                    html.Div([
                        html.Label("Output Folder Name", style={"display": "block", "marginBottom": "4px"}),
                        dcc.Input(
                            id="run-folder-name",
                            type="text",
                            placeholder="auto-generated if blank",
                            debounce=False,
                            style={
                                "width": "360px",
                                "padding": "6px 10px",
                                "backgroundColor": "#1e293b",
                                "color": "#e2e8f0",
                                "border": "1px solid #334155",
                                "borderRadius": "4px",
                                "fontFamily": "monospace",
                                "fontSize": "13px",
                            },
                        ),
                    ]),
                    html.Span(
                        "Leave blank to auto-generate from date range, sport, and timestamp.",
                        style={"color": "#64748b", "fontSize": "12px", "paddingBottom": "6px"},
                    ),
                ],
            ),

            # Config summary + run button
            html.Div(
                style={"display": "flex", "gap": "20px", "alignItems": "center", "marginBottom": "20px"},
                children=[
                    html.Button(
                        "Run Backtest",
                        id="run-backtest-btn",
                        n_clicks=0,
                        style={
                            "padding": "10px 24px",
                            "backgroundColor": "#2563eb",
                            "color": "#fff",
                            "border": "none",
                            "borderRadius": "6px",
                            "fontWeight": "bold",
                            "fontSize": "14px",
                            "cursor": "pointer",
                        },
                    ),
                    html.Div(id="run-config-summary", style={"color": "#aaa", "fontSize": "13px"}),
                ],
            ),

            # Status / output area
            html.Div(
                id="run-status",
                style={
                    **CARD_STYLE,
                    "minHeight": "80px",
                    "whiteSpace": "pre-wrap",
                    "fontFamily": "monospace",
                    "fontSize": "13px",
                },
                children="Ready to run.",
            ),

            # Polling interval (disabled by default)
            dcc.Interval(id="run-poll-interval", interval=1000, disabled=True),
        ])

    def register_callbacks(self, app):

        @app.callback(
            Output("run-start-date", "options"),
            Output("run-start-date", "value"),
            Output("run-end-date", "options"),
            Output("run-end-date", "value"),
            Input("run-sport", "value"),
        )
        def update_dates(sport):
            if not sport:
                return [], None, [], None
            dates = get_dates_for_sport(DATA_DIR, sport)
            options = [{"label": d, "value": d} for d in dates]
            start = dates[-1] if dates else None
            end = dates[0] if dates else None
            return options, start, options, end

        @app.callback(
            Output("run-config-summary", "children"),
            Input("run-dip-thresholds", "value"),
            Input("run-dip-anchors", "value"),
            Input("run-exit-types", "value"),
            Input("run-fee-models", "value"),
        )
        def update_summary(thresholds, anchors, exits, fees):
            thresholds = thresholds or []
            anchors = anchors or []
            exits = exits or []
            fees = fees or []
            combos = len(thresholds) * len(anchors) * len(exits) * len(fees)
            return f"{combos} strategy combos ({len(thresholds)} thresholds x {len(anchors)} anchors x {len(exits)} exits x {len(fees)} fees) per game"

        @app.callback(
            Output("run-status", "children", allow_duplicate=True),
            Output("run-poll-interval", "disabled", allow_duplicate=True),
            Output("run-backtest-btn", "disabled", allow_duplicate=True),
            Input("run-backtest-btn", "n_clicks"),
            State("run-sport", "value"),
            State("run-start-date", "value"),
            State("run-end-date", "value"),
            State("run-dip-thresholds", "value"),
            State("run-dip-anchors", "value"),
            State("run-exit-types", "value"),
            State("run-fee-models", "value"),
            State("run-folder-name", "value"),
            prevent_initial_call=True,
        )
        def start_backtest(n_clicks, sport, start_date, end_date,
                           thresholds, anchors, exit_types, fee_models, folder_name):
            if not n_clicks or _run_state["running"]:
                return no_update, no_update, no_update

            # Validate inputs
            if not all([sport, start_date, end_date, thresholds, anchors, exit_types, fee_models]):
                return "All parameters must be selected.", True, False

            _run_state["running"] = True
            _run_state["output_dir"] = None
            _run_state["error"] = None
            _run_state["progress_msg"] = "Starting..."
            _run_state["games_done"] = 0
            _run_state["games_total"] = 0

            # Launch in background thread
            thread = threading.Thread(
                target=_run_backtest_thread,
                args=(sport, start_date, end_date, thresholds, anchors, exit_types, fee_models, folder_name or ""),
                daemon=True,
            )
            thread.start()

            combos = len(thresholds) * len(anchors) * len(exit_types) * len(fee_models)
            return (
                f"Running backtest...\n"
                f"  Sport: {sport.upper()}\n"
                f"  Date range: {start_date} to {end_date}\n"
                f"  Thresholds: {thresholds}\n"
                f"  Anchors: {anchors}\n"
                f"  Exit types: {exit_types}\n"
                f"  Fee models: {fee_models}\n"
                f"  Total combos per game: {combos}",
                False,  # Enable polling
                True,   # Disable button
            )

        @app.callback(
            Output("run-status", "children"),
            Output("run-poll-interval", "disabled"),
            Output("run-backtest-btn", "disabled"),
            Input("run-poll-interval", "n_intervals"),
        )
        def poll_status(n_intervals):
            if _run_state["running"]:
                done = _run_state["games_done"]
                total = _run_state["games_total"]
                msg = _run_state["progress_msg"]
                if total > 0:
                    bar_filled = int(done / total * 20)
                    bar = "[" + "#" * bar_filled + "-" * (20 - bar_filled) + "]"
                    progress_line = f"{bar} {done}/{total} games\n  {msg}"
                else:
                    progress_line = f"  {msg}"
                return (
                    f"Running backtest...\n\n{progress_line}",
                    no_update,
                    no_update,
                )

            if _run_state["error"]:
                msg = f"Backtest failed:\n{_run_state['error']}"
                return msg, True, False
            if _run_state["output_dir"]:
                output = _run_state["output_dir"]
                return (
                    f"Backtest complete.\n"
                    f"Results saved to: {output}\n\n"
                    f"View results on the Backtest Results tab.",
                    True,   # Stop polling
                    False,  # Re-enable button
                )
            return no_update, no_update, no_update


def _run_backtest_thread(sport, start_date, end_date, thresholds, anchors, exit_types, fee_models, folder_name):
    """Execute backtest in a background thread."""
    try:
        from backtest.backtest_config import DipBuyBacktestConfig
        from backtest.backtest_export import export_backtest_results
        from backtest.backtest_runner import run_backtest_grid

        chart_settings = load_chart_settings(SETTINGS_PATH).to_dict()

        configs = []
        for exit_type in exit_types:
            for fee_model in fee_models:
                for anchor in anchors:
                    config = DipBuyBacktestConfig(
                        dip_thresholds=tuple(sorted(thresholds)),
                        dip_anchor=anchor,
                        exit_type=exit_type,
                        fee_model=fee_model,
                        sport_filter=sport,
                    )
                    configs.append(config)

        sd = datetime.strptime(start_date, "%Y-%m-%d")
        ed = datetime.strptime(end_date, "%Y-%m-%d")

        def progress_callback(msg, games_done, games_total):
            _run_state["progress_msg"] = msg
            _run_state["games_done"] = games_done
            _run_state["games_total"] = games_total

        agg_df, per_game_df = run_backtest_grid(
            start_date=sd,
            end_date=ed,
            configs=configs,
            data_dir=DATA_DIR,
            verbose=False,
            pregame_min_cum_vol=chart_settings.get("pregame_min_cum_vol", 5000),
            open_anchor_stat=chart_settings.get("open_anchor_stat", "vwap"),
            open_anchor_window_min=chart_settings.get("open_anchor_window_min", 5),
            outlier_settings=chart_settings,
            progress_callback=progress_callback,
        )

        _run_state["progress_msg"] = "Aggregating results..."

        if folder_name:
            output_folder = folder_name
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            sport_tag = sport if sport != "all" else "all"
            output_folder = f"{start_date}_{end_date}_{sport_tag}_{timestamp}"

        output_dir = RESULTS_DIR / output_folder
        export_backtest_results(
            aggregated_df=agg_df,
            per_game_df=per_game_df,
            output_dir=str(output_dir),
        )

        _run_state["output_dir"] = str(output_dir)
    except Exception as e:
        logger.exception("Backtest run failed")
        _run_state["error"] = str(e)
    finally:
        _run_state["running"] = False
