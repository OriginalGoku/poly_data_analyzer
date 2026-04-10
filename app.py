"""Dash app for NBA Polymarket game visualization."""

import json
from pathlib import Path

from dash import Dash, Input, Output, callback, dcc, html, no_update
import plotly.graph_objects as go

from charts import build_charts
from loaders import get_available_dates, get_nba_games, load_game
from whales import analyze_whales

DATA_DIR = "data"
SETTINGS_PATH = Path(__file__).parent / "chart_settings.json"


def _load_settings() -> dict:
    with open(SETTINGS_PATH) as f:
        return json.load(f)


SETTINGS = _load_settings()


def _info_row(label, value):
    return html.Div(
        style={"display": "flex", "justifyContent": "space-between",
               "padding": "3px 0", "borderBottom": "1px solid #333"},
        children=[
            html.Span(label, style={"color": "#888"}),
            html.Span(str(value), style={"fontWeight": "bold"}),
        ],
    )


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
                html.Div(
                    style={"flex": "1", "minWidth": "250px", "maxWidth": "300px",
                           "backgroundColor": "#1a1a2e", "padding": "15px",
                           "borderRadius": "8px"},
                    children=[
                        html.H4("Chart Settings", style={"marginTop": 0}),
                        _info_row("Vol Spike Std Dev",
                                  f"{SETTINGS['vol_spike_std']}σ"),
                        _info_row("Vol Spike Lookback",
                                  f"{SETTINGS['vol_spike_lookback']} bars"),
                        _info_row("Pre-Game Min Cum Vol",
                                  f"${SETTINGS['pregame_min_cum_vol']:,}"),
                        _info_row("Post-Game Buffer",
                                  f"{SETTINGS['post_game_buffer_min']} min"),
                        html.Hr(style={"borderColor": "#333", "margin": "8px 0"}),
                        _info_row("Whale Min Vol %",
                                  f"{SETTINGS.get('whale_min_volume_pct', 2.0)}%"),
                        _info_row("Whale Max Count",
                                  SETTINGS.get("whale_max_count", 10)),
                        _info_row("Whale Maker Thresh",
                                  f"{SETTINGS.get('whale_maker_threshold_pct', 60)}%"),
                    ],
                ),
            ],
        ),

        # Whale card
        html.Div(id="whale-card",
                 style={"marginBottom": "20px"}),

        # Charts
        html.H3("Pre-Game", style={"marginTop": "10px", "marginBottom": "5px"}),
        dcc.Loading(
            dcc.Graph(id="pregame-chart", style={"height": "700px"}),
        ),
        html.H3("In-Game", style={"marginTop": "20px", "marginBottom": "5px"}),
        dcc.Loading(
            dcc.Graph(id="game-chart", style={"height": "700px"}),
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
    Output("pregame-chart", "figure"),
    Output("game-chart", "figure"),
    Output("game-card", "children"),
    Output("pregame-card", "children"),
    Output("whale-card", "children"),
    Input("game-picker", "value"),
    Input("date-picker", "value"),
)
def update_game(match_id, date):
    if not match_id or not date:
        return no_update, no_update, no_update, no_update, no_update

    data = load_game(DATA_DIR, date, match_id)
    manifest = data["manifest"]
    trades_df = data["trades_df"]
    trades_meta = data["trades_meta"]

    whale_data = analyze_whales(trades_df, SETTINGS)
    whale_addresses = {w["address"] for w in whale_data["whales"]}

    pregame_fig, game_fig = build_charts(
        trades_df, manifest, data["events"],
        data["tricode_map"], data["gamma_start"], data["gamma_closed"],
        settings=SETTINGS, whale_addresses=whale_addresses,
    )

    # If no tip-off, pregame_fig has all trades, game_fig is None
    if game_fig is None:
        game_fig = go.Figure()
        game_fig.update_layout(
            template="plotly_dark", height=300,
            annotations=[dict(text="No tip-off detected", showarrow=False,
                              xref="paper", yref="paper", x=0.5, y=0.5,
                              font=dict(size=18, color="#888"))],
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

    # Whale card
    whale_card = _build_whale_card(whale_data)

    return pregame_fig, game_fig, game_card, pregame_card, whale_card


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


def _build_whale_card(whale_data: dict):
    """Build whale leaderboard card with two sub-sections."""
    summary = whale_data["summary"]
    whales = whale_data["whales"]

    if not whales:
        return html.Div(
            style={"backgroundColor": "#1a1a2e", "padding": "15px",
                   "borderRadius": "8px"},
            children=[html.H4("Whale Tracker", style={"marginTop": 0}),
                      html.P("No whales detected", style={"color": "#888"})],
        )

    badge_colors = {
        "Market Maker": "#4CAF50",
        "Directional": "#FF5722",
        "Hybrid": "#FFC107",
    }

    def _whale_row(w):
        badge_color = badge_colors.get(w["classification"], "#888")
        return html.Div(
            style={"display": "flex", "justifyContent": "space-between",
                   "alignItems": "center", "padding": "4px 0",
                   "borderBottom": "1px solid #333", "fontSize": "13px"},
            children=[
                html.Span(w["display_addr"], style={"fontFamily": "monospace",
                                                     "minWidth": "120px"}),
                html.Span(f"${w['total_volume']:,.0f}",
                          style={"minWidth": "90px", "textAlign": "right"}),
                html.Span(f"{w['pct_of_total']:.1f}%",
                          style={"minWidth": "50px", "textAlign": "right"}),
                html.Span(w["classification"],
                          style={"backgroundColor": badge_color, "color": "#111",
                                 "padding": "2px 6px", "borderRadius": "4px",
                                 "fontSize": "11px", "fontWeight": "bold",
                                 "minWidth": "90px", "textAlign": "center"}),
                html.Span(w["primary_side"],
                          style={"minWidth": "50px", "textAlign": "right",
                                 "color": "#888"}),
            ],
        )

    # Top Aggressors (by taker_volume)
    by_taker = sorted([w for w in whales if w["taker_volume"] > 0],
                      key=lambda w: w["taker_volume"], reverse=True)[:5]
    # Top Liquidity (by maker_volume)
    by_maker = sorted([w for w in whales if w["maker_volume"] > 0],
                      key=lambda w: w["maker_volume"], reverse=True)[:5]

    return html.Div(
        style={"backgroundColor": "#1a1a2e", "padding": "15px",
               "borderRadius": "8px"},
        children=[
            html.H4("Whale Tracker", style={"marginTop": 0}),
            html.P(
                f"{summary['whale_count']} whales = "
                f"${summary['whale_volume']:,.0f} "
                f"({summary['whale_pct']:.1f}% of volume)",
                style={"color": "#FFD600", "fontWeight": "bold",
                       "marginBottom": "12px"},
            ),
            html.Div(style={"display": "flex", "gap": "20px", "flexWrap": "wrap"},
                     children=[
                html.Div(style={"flex": "1", "minWidth": "300px"}, children=[
                    html.H5("Top Aggressors (Takers)",
                             style={"color": "#FF5722", "marginTop": 0}),
                ] + [_whale_row(w) for w in by_taker]),
                html.Div(style={"flex": "1", "minWidth": "300px"}, children=[
                    html.H5("Top Liquidity (Makers)",
                             style={"color": "#4CAF50", "marginTop": 0}),
                ] + [_whale_row(w) for w in by_maker]),
            ]),
        ],
    )


if __name__ == "__main__":
    app.run(debug=True)
