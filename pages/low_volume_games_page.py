"""Low-volume games inspector.

Lists every collected game whose `pre_game_notional_usdc` falls below an
adjustable threshold (default: `pregame_min_cum_vol` from chart_settings).
Each row links into the main dashboard via the existing `bt_*` deep-link
query parameters so the user can jump straight to the game's chart.
"""
from __future__ import annotations

from urllib.parse import urlencode

import pandas as pd
from dash import Input, Output, State, dash_table, dcc, html

from analytics import load_game_analytics
from view_helpers import CARD_STYLE


class LowVolumeGamesPage:
    route = "/low-volume-games"
    title = "Low-Volume Games"

    def __init__(self, data_dir: str, settings):
        self.data_dir = data_dir
        self.settings = settings

    def layout(self):
        settings_dict = self.settings.to_dict()
        default_threshold = settings_dict.get("pregame_min_cum_vol", 5000)
        return html.Div(
            children=[
                html.H2("Low-Volume Games", style={"marginBottom": "10px"}),
                html.P(
                    "Games filtered out of the main dashboard because pregame "
                    "notional is below the threshold. Click the match-id link "
                    "to open the game in the main dashboard.",
                    style={"color": "#bbb", "marginTop": 0},
                ),
                html.Div(
                    style={
                        **CARD_STYLE,
                        "marginBottom": "20px",
                        "display": "flex",
                        "gap": "16px",
                        "alignItems": "center",
                        "flexWrap": "wrap",
                    },
                    children=[
                        html.Label("Threshold ($)", style={"color": "#bbb"}),
                        dcc.Input(
                            id="low-vol-threshold",
                            type="number",
                            value=default_threshold,
                            min=0,
                            step=100,
                            style={"width": "140px", "color": "#111", "padding": "4px"},
                        ),
                        html.Label("Sport", style={"color": "#bbb"}),
                        dcc.Dropdown(
                            id="low-vol-sport",
                            clearable=False,
                            options=[
                                {"label": "All", "value": "all"},
                                {"label": "NBA", "value": "nba"},
                                {"label": "MLB", "value": "mlb"},
                                {"label": "NHL", "value": "nhl"},
                            ],
                            value="all",
                            style={"width": "140px", "color": "#111"},
                        ),
                        html.Span(id="low-vol-summary", style={"color": "#9ad1ff"}),
                    ],
                ),
                dash_table.DataTable(
                    id="low-vol-table",
                    columns=[
                        {"name": "Date", "id": "date"},
                        {"name": "Sport", "id": "sport"},
                        {
                            "name": "Match",
                            "id": "match_link",
                            "presentation": "markdown",
                        },
                        {"name": "Pregame Vol ($)", "id": "pre_game_notional_usdc", "type": "numeric"},
                        {"name": "Trades", "id": "trade_count", "type": "numeric"},
                    ],
                    markdown_options={"link_target": "_self"},
                    page_size=50,
                    sort_action="native",
                    style_header={
                        "backgroundColor": "#222",
                        "color": "#9ad1ff",
                        "fontWeight": "bold",
                    },
                    style_cell={
                        "backgroundColor": "#1a1a2e",
                        "color": "#eee",
                        "padding": "6px 10px",
                        "fontFamily": "system-ui, sans-serif",
                    },
                    style_data_conditional=[
                        {"if": {"row_index": "odd"}, "backgroundColor": "#15151f"},
                    ],
                ),
            ]
        )

    def register_callbacks(self, app):
        settings_dict = self.settings.to_dict()

        @app.callback(
            Output("low-vol-table", "data"),
            Output("low-vol-summary", "children"),
            Input("low-vol-threshold", "value"),
            Input("low-vol-sport", "value"),
        )
        def populate(threshold, sport):
            try:
                threshold = float(threshold) if threshold is not None else 0.0
            except (TypeError, ValueError):
                threshold = 0.0

            df = load_game_analytics(
                self.data_dir,
                pregame_min_cum_vol=settings_dict.get("pregame_min_cum_vol", 0),
                open_anchor_stat=settings_dict.get("open_anchor_stat", "vwap"),
                open_anchor_window_min=settings_dict.get("open_anchor_window_min", 5),
            )
            if df.empty or "pre_game_notional_usdc" not in df.columns:
                return [], "No analytics data available."

            if sport and sport != "all":
                df = df[df["sport"] == sport].copy()

            below = df[df["pre_game_notional_usdc"].fillna(0) < threshold].copy()
            below = below.sort_values(
                ["pre_game_notional_usdc", "date"], ascending=[True, False]
            )

            rows = [_row_to_record(row) for _, row in below.iterrows()]
            sport_label = sport.upper() if sport and sport != "all" else "all sports"
            summary = (
                f"{len(below)} game{'s' if len(below) != 1 else ''} "
                f"below ${threshold:,.0f} pregame volume "
                f"({sport_label}, of {len(df)} collected)"
            )
            return rows, summary


def _row_to_record(row: pd.Series) -> dict:
    date = row["date"]
    match_id = row["match_id"]
    sport = row.get("sport") or ""
    bt_game = f"{date}|{match_id}"
    qs = urlencode({"bt_sport": sport, "bt_date": date, "bt_game": bt_game})
    link = f"[{match_id}](/?{qs})"
    pre_vol = row.get("pre_game_notional_usdc")
    trade_count = row.get("trade_count")
    return {
        "date": date,
        "sport": (sport or "").upper(),
        "match_link": link,
        "pre_game_notional_usdc": None if pd.isna(pre_vol) else round(float(pre_vol), 2),
        "trade_count": None if pd.isna(trade_count) else int(trade_count),
    }
