"""Scenario runner page — execute scenario JSON specs from the UI."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

from dash import Input, Output, State, dcc, html, no_update

from settings import load_chart_settings
from view_helpers import CARD_STYLE

logger = logging.getLogger(__name__)

DATA_DIR = "data"
RESULTS_DIR = Path("backtest_results")
SCENARIOS_DIR = "backtest/scenarios"
SETTINGS_PATH = Path(__file__).parents[1] / "chart_settings.json"

_run_state = {
    "running": False,
    "output_dir": None,
    "error": None,
    "progress_msg": "",
    "scenarios_done": 0,
    "scenarios_total": 0,
}


def _load_scenario_options():
    try:
        from backtest.scenarios import load_scenarios

        scenarios = load_scenarios(SCENARIOS_DIR)
    except Exception as exc:
        logger.exception("load_scenarios failed: %s", exc)
        return []
    return [{"label": name, "value": name} for name in sorted(scenarios.keys())]


class ScenarioRunnerPage:
    """Configure and run scenario backtests via the new engine."""

    route = "/scenario-runner"
    title = "Scenario Runner"

    def __init__(self):
        pass

    def layout(self):
        scenario_options = _load_scenario_options()
        default_value = [scenario_options[0]["value"]] if scenario_options else []

        return html.Div(children=[
            html.H2("Scenario Runner", style={"marginBottom": "10px"}),
            html.P(
                f"Loaded {len(scenario_options)} scenarios from {SCENARIOS_DIR} (sweep-expanded).",
                style={"color": "#888", "fontSize": "13px"},
            ),

            html.Div(
                style={"display": "flex", "gap": "20px", "marginBottom": "20px", "flexWrap": "wrap"},
                children=[
                    html.Div([
                        html.Label("Scenarios"),
                        dcc.Dropdown(
                            id="scen-picker",
                            options=scenario_options,
                            value=default_value,
                            multi=True,
                            style={"width": "560px", "color": "#111"},
                        ),
                    ]),
                    html.Div([
                        html.Label("Date Range"),
                        dcc.DatePickerRange(
                            id="scen-date-range",
                            display_format="YYYY-MM-DD",
                            start_date_placeholder_text="Start",
                            end_date_placeholder_text="End",
                        ),
                    ]),
                    html.Div([
                        html.Label("Output Folder"),
                        dcc.Input(
                            id="scen-folder-name",
                            type="text",
                            placeholder="auto if blank",
                            style={
                                "width": "260px",
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
                ],
            ),

            html.Div(
                style={"display": "flex", "gap": "20px", "alignItems": "center", "marginBottom": "20px"},
                children=[
                    html.Button(
                        "Run Scenarios",
                        id="scen-run-btn",
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
                    html.Div(id="scen-config-summary", style={"color": "#aaa", "fontSize": "13px"}),
                ],
            ),

            html.Div(
                id="scen-status",
                style={
                    **CARD_STYLE,
                    "minHeight": "80px",
                    "whiteSpace": "pre-wrap",
                    "fontFamily": "monospace",
                    "fontSize": "13px",
                },
                children="Ready to run.",
            ),

            dcc.Interval(id="scen-poll-interval", interval=1000, disabled=True),
        ])

    def register_callbacks(self, app):

        @app.callback(
            Output("scen-config-summary", "children"),
            Input("scen-picker", "value"),
        )
        def update_summary(selected):
            n = len(selected or [])
            return f"{n} scenario(s) selected"

        @app.callback(
            Output("scen-status", "children", allow_duplicate=True),
            Output("scen-poll-interval", "disabled", allow_duplicate=True),
            Output("scen-run-btn", "disabled", allow_duplicate=True),
            Input("scen-run-btn", "n_clicks"),
            State("scen-picker", "value"),
            State("scen-date-range", "start_date"),
            State("scen-date-range", "end_date"),
            State("scen-folder-name", "value"),
            prevent_initial_call=True,
        )
        def start_run(n_clicks, scenario_names, start_date, end_date, folder_name):
            if not n_clicks or _run_state["running"]:
                return no_update, no_update, no_update
            if not scenario_names or not start_date or not end_date:
                return "Select at least one scenario and a date range.", True, False

            _run_state["running"] = True
            _run_state["output_dir"] = None
            _run_state["error"] = None
            _run_state["progress_msg"] = "Starting..."
            _run_state["scenarios_done"] = 0
            _run_state["scenarios_total"] = len(scenario_names)

            thread = threading.Thread(
                target=_run_scenarios_thread,
                args=(list(scenario_names), start_date, end_date, folder_name or ""),
                daemon=True,
            )
            thread.start()

            return (
                f"Running scenarios...\n"
                f"  Scenarios: {len(scenario_names)}\n"
                f"  Date range: {start_date} to {end_date}",
                False,
                True,
            )

        @app.callback(
            Output("scen-status", "children"),
            Output("scen-poll-interval", "disabled"),
            Output("scen-run-btn", "disabled"),
            Input("scen-poll-interval", "n_intervals"),
        )
        def poll_status(n_intervals):
            if _run_state["running"]:
                done = _run_state["scenarios_done"]
                total = _run_state["scenarios_total"]
                msg = _run_state["progress_msg"]
                if total > 0:
                    bar_filled = int(done / total * 20)
                    bar = "[" + "#" * bar_filled + "-" * (20 - bar_filled) + "]"
                    line = f"{bar} {done}/{total} scenarios\n  {msg}"
                else:
                    line = f"  {msg}"
                return f"Running scenarios...\n\n{line}", no_update, no_update

            if _run_state["error"]:
                return f"Run failed:\n{_run_state['error']}", True, False
            if _run_state["output_dir"]:
                output = _run_state["output_dir"]
                return (
                    f"Run complete.\n"
                    f"Results saved to: {output}\n\n"
                    f"View on the Scenario Results tab.",
                    True,
                    False,
                )
            return no_update, no_update, no_update


def _run_scenarios_thread(scenario_names, start_date, end_date, folder_name):
    try:
        from backtest.backtest_export import export_backtest_results
        from backtest.runner import run as runner_run
        from backtest.scenarios import load_scenarios

        chart_settings = load_chart_settings(SETTINGS_PATH).to_dict()
        all_scenarios = load_scenarios(SCENARIOS_DIR)
        selected = [all_scenarios[n] for n in scenario_names if n in all_scenarios]
        if not selected:
            raise ValueError("No matching scenarios were resolved from selection.")

        sd = datetime.strptime(start_date[:10], "%Y-%m-%d")
        ed = datetime.strptime(end_date[:10], "%Y-%m-%d")

        def progress_callback(done, total, msg):
            _run_state["scenarios_done"] = int(done)
            _run_state["scenarios_total"] = int(total)
            _run_state["progress_msg"] = str(msg)

        per_position_df, aggregation_df = runner_run(
            scenarios=selected,
            start_date=sd,
            end_date=ed,
            data_dir=DATA_DIR,
            settings=chart_settings,
            progress_callback=progress_callback,
        )

        _run_state["progress_msg"] = "Exporting..."

        if folder_name:
            output_folder = folder_name
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_folder = f"scenario_{start_date[:10]}_{end_date[:10]}_{timestamp}"
        output_dir = RESULTS_DIR / output_folder

        sweep_cols = [c for c in aggregation_df.columns if c.startswith("sweep_axis_")]
        heatmap_dims = None
        if len(sweep_cols) >= 2:
            heatmap_dims = (sweep_cols[0], sweep_cols[1])
        elif len(sweep_cols) == 1:
            heatmap_dims = (sweep_cols[0], sweep_cols[0])

        export_backtest_results(
            per_position_df=per_position_df,
            aggregation_df=aggregation_df,
            output_path=str(output_dir),
            heatmap_dims=heatmap_dims,
        )

        _run_state["output_dir"] = str(output_dir)
    except Exception as e:
        logger.exception("Scenario run failed")
        _run_state["error"] = str(e)
    finally:
        _run_state["running"] = False
