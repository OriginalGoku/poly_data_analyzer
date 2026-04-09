"""Dash app for NBA Polymarket game visualization."""

from dash import Dash, Input, Output, callback, dcc, html, no_update

from charts import build_price_chart
from loaders import get_available_dates, get_nba_games, load_game

DATA_DIR = "data"

app = Dash(__name__)

app.layout = html.Div(
    style={"backgroundColor": "#111", "minHeight": "100vh", "padding": "20px",
           "fontFamily": "system-ui, sans-serif", "color": "#eee"},
    children=[
        html.H2("NBA Game Visualizer", style={"marginBottom": "10px"}),

        # Controls
        html.Div(
            style={"display": "flex", "gap": "20px", "marginBottom": "20px"},
            children=[
                html.Div([
                    html.Label("Date"),
                    dcc.Dropdown(id="date-picker", clearable=False,
                                 style={"width": "200px", "color": "#111"}),
                ]),
                html.Div([
                    html.Label("Game"),
                    dcc.Dropdown(id="game-picker", clearable=False,
                                 style={"width": "350px", "color": "#111"}),
                ]),
            ],
        ),

        # Info cards
        html.Div(
            style={"display": "flex", "gap": "20px", "marginBottom": "20px",
                    "flexWrap": "wrap"},
            children=[
                html.Div(id="game-card",
                         style={"flex": "1", "minWidth": "300px",
                                "backgroundColor": "#1a1a2e", "padding": "15px",
                                "borderRadius": "8px"}),
                html.Div(id="pregame-card",
                         style={"flex": "1", "minWidth": "300px",
                                "backgroundColor": "#1a1a2e", "padding": "15px",
                                "borderRadius": "8px"}),
            ],
        ),

        # Chart
        dcc.Loading(
            dcc.Graph(id="main-chart", style={"height": "800px"}),
        ),
    ],
)


@callback(Output("date-picker", "options"), Output("date-picker", "value"),
          Input("date-picker", "id"))
def populate_dates(_):
    """Populate date dropdown, default to most recent date with NBA games."""
    dates = get_available_dates(DATA_DIR)
    # Find first date with NBA games
    default = dates[0] if dates else None
    for d in dates:
        games = get_nba_games(DATA_DIR, d)
        if games:
            default = d
            break
    options = [{"label": d, "value": d} for d in dates]
    return options, default


@callback(Output("game-picker", "options"), Output("game-picker", "value"),
          Input("date-picker", "value"))
def populate_games(date):
    if not date:
        return [], None
    games = get_nba_games(DATA_DIR, date)
    options = [
        {"label": f"{g['away_team']} @ {g['home_team']}", "value": g["match_id"]}
        for g in games
    ]
    value = options[0]["value"] if options else None
    return options, value


@callback(
    Output("main-chart", "figure"),
    Output("game-card", "children"),
    Output("pregame-card", "children"),
    Input("game-picker", "value"),
    Input("date-picker", "value"),
)
def update_game(match_id, date):
    if not match_id or not date:
        return no_update, no_update, no_update

    data = load_game(DATA_DIR, date, match_id)
    manifest = data["manifest"]
    trades_df = data["trades_df"]
    trades_meta = data["trades_meta"]

    fig = build_price_chart(
        trades_df, manifest, data["events"],
        data["tricode_map"], data["gamma_start"], data["gamma_closed"],
    )

    # Game metadata card
    away = manifest["outcomes"][0]
    home = manifest["outcomes"][1]
    volume = manifest.get("volume_stats", {})
    cp_meta = trades_meta.get("price_checkpoints_meta", {})
    price_quality = cp_meta.get("price_quality", "unknown") if cp_meta else "unknown"

    game_card = [
        html.H4(f"{away} @ {home}", style={"marginTop": 0}),
        _info_row("Final", f"{manifest.get('is_final', '?')}"),
        _info_row("Trades", f"{volume.get('trade_count', len(trades_df)):,}"),
        _info_row("Total Volume", f"${volume.get('total_notional_usdc', 0):,.0f}"),
        _info_row("Price Quality", price_quality),
        _info_row("Source", trades_meta.get("history_source", "?")),
        _info_row("Truncated", str(trades_meta.get("history_truncated", False))),
    ]

    # Pre-game summary card
    pregame_card = _build_pregame_card(trades_df, trades_meta, data, manifest)

    return fig, game_card, pregame_card


def _build_pregame_card(trades_df, trades_meta, data, manifest):
    """Build pre-game summary card content."""
    tip_off = None
    if data["events"]:
        for ev in data["events"]:
            if ev.get("time_actual_dt"):
                tip_off = ev["time_actual_dt"]
                break

    away_token = manifest["token_ids"][0]
    away_team = manifest["outcomes"][0]

    # Opening price from price_checkpoints
    checkpoints = trades_meta.get("price_checkpoints", {})
    away_cp = checkpoints.get(away_token, {}) if checkpoints else {}
    opening_price = away_cp.get("selected_early_price")
    opening_source = away_cp.get("selected_early_price_source", "unknown")

    # Pre-game stats
    if tip_off is not None:
        pre = trades_df[trades_df["datetime"] < tip_off]
    else:
        pre = trades_df  # no tip-off — all trades are "pre-game"

    pre_away = pre[pre["asset"] == away_token]
    last_pre_price = pre_away.iloc[-1]["price"] if not pre_away.empty else None

    drift = None
    if opening_price and last_pre_price:
        drift = last_pre_price - opening_price

    return [
        html.H4("Pre-Game Summary", style={"marginTop": 0}),
        _info_row(f"Opening ({away_team})",
                  f"{opening_price:.3f} ({opening_source})" if opening_price else "N/A"),
        _info_row(f"Last Pre-Tipoff ({away_team})",
                  f"{last_pre_price:.3f}" if last_pre_price else "N/A"),
        _info_row("Drift",
                  f"{drift:+.3f}" if drift is not None else "N/A"),
        _info_row("Pre-Game Trades", f"{len(pre):,}"),
        _info_row("Pre-Game Volume", f"${pre['size'].sum():,.0f}"),
    ]


def _info_row(label, value):
    return html.Div(
        style={"display": "flex", "justifyContent": "space-between",
               "padding": "3px 0", "borderBottom": "1px solid #333"},
        children=[
            html.Span(label, style={"color": "#888"}),
            html.Span(str(value), style={"fontWeight": "bold"}),
        ],
    )


if __name__ == "__main__":
    app.run(debug=True)
