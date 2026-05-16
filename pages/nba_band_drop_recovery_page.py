"""NBA Band Drop Recovery page.

Renders a 2D grid of conditional recovery base rates:
    rows    = open interpretable bands (Lean Favorite ... Upper Strong)
    columns = drop-pct buckets [10, 20, 30, 40, 50, 60, 70, 80, 90, 95]
    cells   = recovery_rate (N), Wilson 95% CI shown in the detail table

The page owns its own engine invocation against the
``band_drop_recovery_sweep`` scenario.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from dash import Input, Output, State, dash_table, dcc, html

import backtest.exits  # noqa: F401  (populate registries)
import backtest.filters  # noqa: F401
import backtest.triggers  # noqa: F401
from analytics import ACTIVE_INTERPRETABLE_BAND_LABELS, load_game_analytics
from backtest.runner import run as run_scenarios
from backtest.scenarios import load_scenarios
from band_drop_recovery import compute_recovery_grid, partition_games
from view_helpers import CARD_STYLE, info_row


DROP_PCTS = (10, 20, 30, 40, 50, 60, 70, 80, 90, 95)
SCENARIO_NAME_PREFIX = "band_drop_recovery_sweep"
DATA_DIR = "data"


class NBABandDropRecoveryPage:
    """Per-band drop-recovery base rate explorer."""

    route = "/nba-band-drop-recovery"
    title = "NBA Band Drop Recovery"

    def __init__(self, settings):
        self.settings = settings

    def layout(self):
        settings_dict = self.settings.to_dict()
        return html.Div(
            children=[
                html.H2("NBA Band Drop Recovery", style={"marginBottom": "10px"}),
                html.P(
                    "Given the favorite was in band B at tipoff and its price dropped X% intraday, "
                    "what fraction of those games saw price recover to >= the tipoff price before game end?",
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
                        html.Ul(
                            style={"margin": 0, "color": "#d7e6ff", "fontSize": "13px", "lineHeight": "1.5"},
                            children=[
                                html.Li("Drop is a relative percentage measured from the favorite's tipoff price (not from open)."),
                                html.Li("First-touch semantics: the first in-game trade at or below tipoff x (1 - X/100) defines the entry; one entry per (game, drop-pct) by construction."),
                                html.Li("Recovery is strict: exit triggered by the first subsequent trade at price >= the tipoff price; otherwise the position is forced-closed at game end."),
                                html.Li("Cumulative: deeper buckets are subsets of shallower ones (a 50% drop also satisfied 10/20/30/40), so cell N values are non-increasing across the row from left to right."),
                                html.Li("Toss-Up games are excluded by the minimum open favorite price filter; the aggregator drops any remaining Toss-Up rows defensively."),
                                html.Li("Disclaimer: this is a base rate over historical recovery only; it does not adjust for PnL, fees, or maker/taker mix."),
                            ],
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
                                    id="bdr-price-quality",
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
                                html.Label("Start Date (YYYY-MM-DD)"),
                                dcc.Input(
                                    id="bdr-start-date",
                                    type="text",
                                    placeholder="2024-10-01",
                                    style={"width": "180px"},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Label("End Date (YYYY-MM-DD)"),
                                dcc.Input(
                                    id="bdr-end-date",
                                    type="text",
                                    placeholder="2026-05-16",
                                    style={"width": "180px"},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Label("Min Open Favorite Price"),
                                dcc.Input(
                                    id="bdr-min-open-fav",
                                    type="number",
                                    value=float(settings_dict.get("analysis_min_open_favorite_price", 0.50)),
                                    step=0.01,
                                    min=0.0,
                                    max=1.0,
                                    style={"width": "120px"},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Label("Min N to Display"),
                                dcc.Input(
                                    id="bdr-min-n",
                                    type="number",
                                    value=5,
                                    min=1,
                                    step=1,
                                    style={"width": "120px"},
                                ),
                            ]
                        ),
                        html.Div(
                            style={"alignSelf": "flex-end"},
                            children=[
                                html.Button(
                                    "Run",
                                    id="bdr-run",
                                    n_clicks=0,
                                    style={
                                        "padding": "8px 16px",
                                        "backgroundColor": "#9ad1ff",
                                        "color": "#111",
                                        "border": "none",
                                        "borderRadius": "6px",
                                        "fontWeight": "bold",
                                        "cursor": "pointer",
                                    },
                                ),
                            ],
                        ),
                    ],
                ),
                html.Div(
                    style={"display": "flex", "gap": "20px", "marginBottom": "20px", "flexWrap": "wrap"},
                    children=[
                        html.Div(id="bdr-run-summary", style={**CARD_STYLE, "flex": "1", "minWidth": "320px"}),
                        html.Div(
                            style={**CARD_STYLE, "flex": "1", "minWidth": "280px", "maxWidth": "320px"},
                            children=[
                                html.H4("Noise Controls", style={"marginTop": 0}),
                                info_row("Sport", "NBA"),
                                info_row("Open Anchor", settings_dict["open_anchor_stat"].upper()),
                                info_row("Open Anchor Window", f"{settings_dict['open_anchor_window_min']} min"),
                                info_row("Pre-Game Min Cum Vol", f"${settings_dict['pregame_min_cum_vol']:,}"),
                            ],
                        ),
                    ],
                ),
                html.H3("Recovery Rate Grid", style={"marginBottom": "10px"}),
                html.Div(id="bdr-grid-container"),
                html.Details(
                    style={"marginTop": "20px"},
                    children=[
                        html.Summary("Per-bucket detail", style={"cursor": "pointer", "color": "#9ad1ff"}),
                        html.Div(id="bdr-detail-container", style={"marginTop": "10px"}),
                    ],
                ),
                dcc.Store(id="bdr-error"),
            ]
        )

    def register_callbacks(self, app):
        @app.callback(
            Output("bdr-run-summary", "children"),
            Output("bdr-grid-container", "children"),
            Output("bdr-detail-container", "children"),
            Input("bdr-run", "n_clicks"),
            State("bdr-price-quality", "value"),
            State("bdr-start-date", "value"),
            State("bdr-end-date", "value"),
            State("bdr-min-open-fav", "value"),
            State("bdr-min-n", "value"),
        )
        def run_callback(n_clicks, price_quality, start_date, end_date, min_open_fav, min_n_display):
            try:
                return _run_and_render(
                    self.settings,
                    price_quality=price_quality or "all",
                    start_date=start_date or None,
                    end_date=end_date or None,
                    min_open_fav=float(min_open_fav) if min_open_fav is not None else 0.50,
                    min_n_display=int(min_n_display) if min_n_display else 5,
                )
            except Exception as exc:  # surface errors in the UI instead of crashing
                err = html.Div(
                    style={"color": "#ff8b8b"},
                    children=[html.Strong("Error: "), html.Span(str(exc))],
                )
                return err, None, None


def _run_and_render(
    settings,
    *,
    price_quality: str,
    start_date: str | None,
    end_date: str | None,
    min_open_fav: float,
    min_n_display: int,
):
    settings_dict = settings.to_dict()
    base_records = load_game_analytics(
        DATA_DIR,
        pregame_min_cum_vol=float(settings_dict["pregame_min_cum_vol"]),
        open_anchor_stat=str(settings_dict["open_anchor_stat"]),
        open_anchor_window_min=int(settings_dict["open_anchor_window_min"]),
    )
    if base_records is None or base_records.empty:
        raise RuntimeError(
            "Base-records cache is empty. Open the main dashboard or NBA Open vs Tip-Off "
            "page first to populate `cache/_base_records/`."
        )

    partition = partition_games(
        base_records,
        {
            "sport": "nba",
            "start_date": start_date,
            "end_date": end_date,
            "price_quality": price_quality,
            "min_open_favorite_price": min_open_fav,
        },
    )

    scenarios = _load_band_drop_recovery_scenarios()
    sd = _parse_date(start_date) or datetime(1970, 1, 1)
    ed = _parse_date(end_date) or datetime(2099, 12, 31)
    positions_df, _ = run_scenarios(scenarios, sd, ed, DATA_DIR, settings_dict)

    if not positions_df.empty:
        keep = partition["kept_match_ids"]
        positions_df = positions_df[
            positions_df.apply(
                lambda r: (str(r["date"]), str(r["match_id"])) in keep, axis=1
            )
        ].copy()

    out = compute_recovery_grid(
        positions_df,
        base_records[base_records["sport"] == "nba"],
        ACTIVE_INTERPRETABLE_BAND_LABELS,
        DROP_PCTS,
        min_n_display=min_n_display,
    )

    grid_n = int(len(positions_df))
    summary = [
        html.H4("Run Summary", style={"marginTop": 0}),
        info_row("NBA Games (post-filter)", f"{partition['total']:,}"),
        info_row("Excluded (no tipoff price)", f"{partition['excluded_missing_tipoff']:,}"),
        info_row("Grid Positions (sum across cells)", f"{grid_n:,}"),
    ]
    return summary, _build_grid_table(out["grid"], min_n_display), _build_detail_table(out["detail"])


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d")


def _load_band_drop_recovery_scenarios():
    scenarios_dir = "backtest/scenarios"
    sweep_path = os.path.join(scenarios_dir, "band_drop_recovery_sweep.json")
    if not os.path.exists(sweep_path):
        raise RuntimeError(f"Missing scenario file: {sweep_path}")
    try:
        all_scenarios = load_scenarios(scenarios_dir)
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to load scenarios: {exc}") from exc
    matching = [s for n, s in all_scenarios.items() if n.startswith(SCENARIO_NAME_PREFIX)]
    if not matching:
        raise RuntimeError(f"No scenarios found with prefix {SCENARIO_NAME_PREFIX!r}.")
    return matching


def _format_cell(cell, min_n_display: int) -> str:
    if not isinstance(cell, dict) or cell.get("n", 0) == 0:
        return "—"
    n = cell["n"]
    rate = cell["rate"]
    if rate is None:
        return "—"
    star = "*" if 0 < n < min_n_display else ""
    return f"{rate * 100:.0f}%{star} ({n})"


def _build_grid_table(grid: pd.DataFrame, min_n_display: int):
    rows = []
    for band in grid.index:
        row = {"Band": band}
        for col in grid.columns:
            cell = grid.at[band, col]
            row[f"{int(col)}%"] = _format_cell(cell, min_n_display)
        rows.append(row)
    columns = [{"name": "Band", "id": "Band"}] + [
        {"name": f"{int(c)}%", "id": f"{int(c)}%"} for c in grid.columns
    ]
    return dash_table.DataTable(
        id="bdr-grid",
        data=rows,
        columns=columns,
        style_table={"overflowX": "auto"},
        style_cell={
            "backgroundColor": "#141422",
            "color": "#eee",
            "border": "1px solid #333",
            "padding": "8px",
            "textAlign": "center",
            "fontFamily": "system-ui, sans-serif",
        },
        style_header={
            "backgroundColor": "#1f1f33",
            "fontWeight": "bold",
            "border": "1px solid #333",
        },
    )


def _build_detail_table(detail: pd.DataFrame):
    if detail.empty:
        return html.Div("No detail rows.", style={"color": "#888"})

    def _fmt_pct(v):
        return "—" if v is None or pd.isna(v) else f"{float(v) * 100:.1f}%"

    def _fmt_sec(v):
        return "—" if v is None or pd.isna(v) else f"{float(v):.0f}s"

    rows = []
    for _, r in detail.iterrows():
        rows.append(
            {
                "Band": r["band"],
                "Drop %": int(r["drop_pct"]),
                "N": int(r["n"]),
                "Successes": int(r["successes"]),
                "Recovery Rate": _fmt_pct(r["recovery_rate"]),
                "Wilson Low": _fmt_pct(r["wilson_lo"]),
                "Wilson High": _fmt_pct(r["wilson_hi"]),
                "Median Time to Recovery": _fmt_sec(r["median_time_to_recovery_seconds"]),
                "Median Further Drawdown": _fmt_pct(r["median_further_drawdown_pct"]),
            }
        )
    columns = [{"name": k, "id": k} for k in rows[0].keys()]
    return dash_table.DataTable(
        id="bdr-detail",
        data=rows,
        columns=columns,
        sort_action="native",
        page_size=25,
        style_table={"overflowX": "auto"},
        style_cell={
            "backgroundColor": "#141422",
            "color": "#eee",
            "border": "1px solid #333",
            "padding": "6px",
            "textAlign": "left",
            "fontFamily": "system-ui, sans-serif",
        },
        style_header={
            "backgroundColor": "#1f1f33",
            "fontWeight": "bold",
            "border": "1px solid #333",
        },
    )
