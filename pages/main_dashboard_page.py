"""Main game dashboard page."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dcc, html, no_update

from analytics import ACTIVE_INTERPRETABLE_BAND_LABELS, build_analysis_summary, get_analytics_view
from charts import (
    build_charts,
    build_discrepancy_intervals_chart,
    build_score_chart,
    build_score_diff_chart,
    build_sensitivity_surface,
    build_sensitivity_timeline,
)
from discrepancy import load_or_compute_discrepancies
from loaders import get_available_sports_from_manifests, get_dates_for_sport, get_games_for_date_and_sport
from sensitivity import load_or_compute_sensitivity
from view_helpers import CARD_STYLE, info_row, format_prob, format_quantile_cutoffs
from whales import analyze_whales


class MainDashboardPage:
    """Wrap the legacy single-game dashboard as a reusable page."""

    route = "/"
    title = "Main Dashboard"

    def __init__(self, data_dir: str, settings):
        self.data_dir = data_dir
        self.settings = settings

    def layout(self):
        settings_dict = self.settings.to_dict()
        return html.Div(
            children=[
                html.H2("Poly Data Analyzer", style={"marginBottom": "10px"}),
                html.Div(
                    style={"display": "flex", "gap": "20px", "marginBottom": "20px"},
                    children=[
                        html.Div(
                            [
                                html.Label("Sport"),
                                dcc.Dropdown(
                                    id="sport-picker",
                                    clearable=False,
                                    style={"width": "160px", "color": "#111"},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Label("Start Date"),
                                dcc.Dropdown(
                                    id="start-date-picker",
                                    clearable=False,
                                    style={"width": "200px", "color": "#111"},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Label("End Date"),
                                dcc.Dropdown(
                                    id="end-date-picker",
                                    clearable=False,
                                    style={"width": "200px", "color": "#111"},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Label("Price Quality"),
                                dcc.Dropdown(
                                    id="price-quality-picker",
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
                                html.Label("Open Bucket"),
                                dcc.Dropdown(
                                    id="bucket-picker",
                                    clearable=False,
                                    options=[{"label": "All", "value": "all"}]
                                    + [
                                        {"label": label, "value": label}
                                        for label in ACTIVE_INTERPRETABLE_BAND_LABELS
                                    ],
                                    value="all",
                                    style={"width": "220px", "color": "#111"},
                                ),
                            ]
                        ),
                        html.Div(
                            [
                                html.Label("Game"),
                                dcc.Dropdown(
                                    id="game-picker",
                                    clearable=False,
                                    style={"width": "420px", "color": "#111"},
                                ),
                            ]
                        ),
                    ],
                ),
                html.Div(
                    style={"display": "flex", "gap": "20px", "marginBottom": "20px", "flexWrap": "wrap"},
                    children=[
                        html.Div(id="game-card", style={**CARD_STYLE, "flex": "1", "minWidth": "300px"}),
                        html.Div(id="pregame-card", style={**CARD_STYLE, "flex": "1", "minWidth": "300px"}),
                        html.Div(id="analysis-card", style={**CARD_STYLE, "flex": "1", "minWidth": "320px"}),
                        html.Div(
                            style={
                                **CARD_STYLE,
                                "flex": "1",
                                "minWidth": "250px",
                                "maxWidth": "300px",
                            },
                            children=[
                                html.H4("Chart Settings", style={"marginTop": 0}),
                                info_row("Open Anchor", settings_dict.get("open_anchor_stat", "vwap").upper()),
                                info_row(
                                    "Open Anchor Window",
                                    f"{settings_dict.get('open_anchor_window_min', 5)} min",
                                ),
                                info_row("Vol Spike Std Dev", f"{settings_dict['vol_spike_std']}σ"),
                                info_row("Vol Spike Lookback", f"{settings_dict['vol_spike_lookback']} bars"),
                                info_row("Pre-Game Min Cum Vol", f"${settings_dict['pregame_min_cum_vol']:,}"),
                                info_row(
                                    "Min Open Favorite Price",
                                    f"{settings_dict.get('analysis_min_open_favorite_price', 0.5):.2f}",
                                ),
                                info_row("Post-Game Buffer", f"{settings_dict['post_game_buffer_min']} min"),
                                html.Hr(style={"borderColor": "#333", "margin": "8px 0"}),
                                info_row("Whale Min Vol %", f"{settings_dict['whale_min_volume_pct']}%"),
                                info_row("Whale Max Count", settings_dict["whale_max_count"]),
                                info_row("Whale Maker Thresh", f"{settings_dict['whale_maker_threshold_pct']}%"),
                                info_row("Whale Marker Min Trade %", f"{settings_dict['whale_marker_min_trade_pct']}%"),
                            ],
                        ),
                    ],
                ),
                html.Div(id="whale-card", style={"marginBottom": "20px"}),
                html.H3("Pre-Game", style={"marginTop": "10px", "marginBottom": "5px"}),
                dcc.Loading(dcc.Graph(id="pregame-chart", style={"height": "700px"})),
                html.H3("Score Progression", style={"marginTop": "20px", "marginBottom": "5px"}),
                dcc.Loading(dcc.Graph(id="score-chart", style={"height": "360px"})),
                html.H3("Lead Difference", style={"marginTop": "20px", "marginBottom": "5px"}),
                dcc.Loading(dcc.Graph(id="score-diff-chart", style={"height": "280px"})),
                html.H3("Price Sensitivity to Scoring", style={"marginTop": "20px", "marginBottom": "5px"}),
                dcc.Loading(dcc.Graph(id="sensitivity-timeline", style={"height": "360px"})),
                html.H3("Sensitivity by Game Phase & Score Gap", style={"marginTop": "20px", "marginBottom": "5px"}),
                dcc.Loading(dcc.Graph(id="sensitivity-surface", style={"height": "520px"})),
                html.H3("Market-Score Discrepancies", style={"marginTop": "20px", "marginBottom": "5px"}),
                dcc.Loading(dcc.Graph(id="discrepancy-chart", style={"height": "360px"})),
                html.H3("In-Game", style={"marginTop": "20px", "marginBottom": "5px"}),
                dcc.Loading(dcc.Graph(id="game-chart", style={"height": "700px"})),
            ]
        )

    def register_callbacks(self, app):
        settings_dict = self.settings.to_dict()

        @app.callback(Output("sport-picker", "options"), Output("sport-picker", "value"), Input("sport-picker", "id"))
        def populate_sports(_):
            sports = get_available_sports_from_manifests(self.data_dir)
            options = [{"label": sport.upper(), "value": sport} for sport in sports]
            default = "nba" if "nba" in sports else (sports[0] if sports else None)
            return options, default

        @app.callback(
            Output("game-picker", "options"),
            Output("game-picker", "value"),
            Input("start-date-picker", "value"),
            Input("end-date-picker", "value"),
            Input("sport-picker", "value"),
            Input("price-quality-picker", "value"),
            Input("bucket-picker", "value"),
        )
        def populate_games(start_date, end_date, sport, price_quality, bucket):
            if not start_date or not end_date or not sport:
                return [], None
            start_date, end_date = _normalize_date_range(start_date, end_date)
            analytics = get_analytics_view(
                self.data_dir,
                sport=sport,
                price_quality_filter=price_quality,
                pregame_min_cum_vol=settings_dict.get("pregame_min_cum_vol", 0),
                open_anchor_stat=settings_dict.get("open_anchor_stat", "vwap"),
                open_anchor_window_min=settings_dict.get("open_anchor_window_min", 5),
                start_date=start_date,
                end_date=end_date,
            )
            if bucket and bucket != "all":
                analytics = analytics[analytics["open_interpretable_band"] == bucket].copy()
            options = [
                {
                    "label": f"{row['date']} | {row['label']} | {row['open_interpretable_band']}",
                    "value": _encode_game_value(row["date"], row["match_id"]),
                }
                for _, row in analytics.iterrows()
            ]
            value = options[0]["value"] if options else None
            return options, value

        @app.callback(
            Output("start-date-picker", "options"),
            Output("start-date-picker", "value"),
            Output("end-date-picker", "options"),
            Output("end-date-picker", "value"),
            Input("sport-picker", "value"),
            Input("price-quality-picker", "value"),
        )
        def populate_dates(sport, price_quality):
            if not sport:
                return [], None, [], None
            dates = get_dates_for_sport(self.data_dir, sport)
            options = [{"label": date, "value": date} for date in dates]
            start, end = _default_date_window(dates)
            return options, start, options, end

        @app.callback(
            Output("pregame-chart", "figure"),
            Output("game-chart", "figure"),
            Output("score-chart", "figure"),
            Output("score-diff-chart", "figure"),
            Output("sensitivity-timeline", "figure"),
            Output("sensitivity-surface", "figure"),
            Output("discrepancy-chart", "figure"),
            Output("game-card", "children"),
            Output("pregame-card", "children"),
            Output("analysis-card", "children"),
            Output("whale-card", "children"),
            Input("game-picker", "value"),
            Input("start-date-picker", "value"),
            Input("end-date-picker", "value"),
            Input("sport-picker", "value"),
            Input("price-quality-picker", "value"),
            Input("bucket-picker", "value"),
        )
        def update_game(selected_game, start_date, end_date, sport, price_quality_filter, bucket):
            if not selected_game or not start_date or not end_date or not sport:
                return (
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                )
            game_date, match_id = _decode_game_value(selected_game)
            start_date, end_date = _normalize_date_range(start_date, end_date)

            analytics = get_analytics_view(
                self.data_dir,
                sport=sport,
                price_quality_filter=price_quality_filter,
                pregame_min_cum_vol=settings_dict.get("pregame_min_cum_vol", 0),
                open_anchor_stat=settings_dict.get("open_anchor_stat", "vwap"),
                open_anchor_window_min=settings_dict.get("open_anchor_window_min", 5),
                start_date=start_date,
                end_date=end_date,
            )
            if bucket and bucket != "all":
                analytics = analytics[analytics["open_interpretable_band"] == bucket].copy()
            game_row = analytics[(analytics["match_id"] == match_id) & (analytics["date"] == game_date)]
            if game_row.empty:
                return (
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                )
            game_row = game_row.iloc[0]
            analysis_summary = build_analysis_summary(game_row, analytics)

            from loaders import load_game

            data = load_game(self.data_dir, game_date, match_id)
            manifest = data["manifest"]
            trades_df = data["trades_df"]
            trades_meta = data["trades_meta"]

            whale_data = analyze_whales(trades_df, settings_dict)
            whale_addresses = {whale["address"] for whale in whale_data["whales"]}
            top_taker_whales = sorted(
                [
                    whale
                    for whale in whale_data["whales"]
                    if whale["taker_volume"] > 0 and whale["classification"] != "Market Maker"
                ],
                key=lambda whale: whale["taker_volume"],
                reverse=True,
            )[:10]

            pregame_fig, game_fig = build_charts(
                trades_df,
                manifest,
                data["events"],
                data["tricode_map"],
                data["gamma_start"],
                data["gamma_closed"],
                settings=settings_dict,
                whale_addresses=whale_addresses,
                top_taker_whales=top_taker_whales,
            )
            score_fig = build_score_chart(manifest, data["events"])
            score_diff_fig = build_score_diff_chart(manifest, data["events"])
            cache_dir = Path(__file__).parent.parent / "cache"
            sensitivity_df = load_or_compute_sensitivity(
                cache_dir,
                game_date,
                match_id,
                trades_df,
                data["events"],
                manifest,
                self.settings,
            )
            sensitivity_timeline_fig = build_sensitivity_timeline(
                sensitivity_df,
                manifest,
                data["events"],
            )
            sensitivity_surface_fig = build_sensitivity_surface(
                sensitivity_df,
                manifest,
                self.settings,
            )
            discrepancy_df = load_or_compute_discrepancies(
                cache_dir,
                game_date,
                match_id,
                trades_df,
                data["events"],
                manifest,
                self.settings,
            )
            discrepancy_fig = build_discrepancy_intervals_chart(
                discrepancy_df,
                manifest,
            )

            if game_fig is None:
                game_fig = go.Figure()
                game_fig.update_layout(
                    template="plotly_dark",
                    height=300,
                    annotations=[
                        {
                            "text": "No tip-off detected",
                            "showarrow": False,
                            "xref": "paper",
                            "yref": "paper",
                            "x": 0.5,
                            "y": 0.5,
                            "font": {"size": 18, "color": "#888"},
                        }
                    ],
                )

            volume = manifest.get("volume_stats", {})
            cp_meta = trades_meta.get("price_checkpoints_meta", {})
            game_price_quality = cp_meta.get("price_quality", "unknown") if cp_meta else "unknown"

            game_card = [
                html.H4(f"{manifest['outcomes'][0]} @ {manifest['outcomes'][1]}", style={"marginTop": 0}),
                info_row("Sport", manifest.get("sport", "?").upper()),
                info_row("Final", f"{manifest.get('is_final', '?')}"),
                info_row("Trades", f"{volume.get('trade_count', len(trades_df)):,}"),
                info_row("Total Volume", f"${volume.get('total_notional_usdc', 0):,.0f}"),
                info_row("Price Quality", game_price_quality),
                info_row("Source", trades_meta.get("history_source", "?")),
                info_row("Truncated", str(trades_meta.get("history_truncated", False))),
            ]

            pregame_card = _build_pregame_card(trades_df, data, manifest, analysis_summary)
            whale_card = _build_whale_card(whale_data)
            analysis_card = _build_analysis_card(analysis_summary, price_quality_filter)
            return (
                pregame_fig,
                game_fig,
                score_fig,
                score_diff_fig,
                sensitivity_timeline_fig,
                sensitivity_surface_fig,
                discrepancy_fig,
                game_card,
                pregame_card,
                analysis_card,
                whale_card,
            )


def _default_date_window(dates: list[str]) -> tuple[str | None, str | None]:
    if not dates:
        return None, None
    parsed = pd.to_datetime(dates)
    end = parsed.max()
    target_start = end - timedelta(days=30)
    eligible = parsed[parsed >= target_start]
    start = eligible.min() if len(eligible) else parsed.min()
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _normalize_date_range(start_date: str, end_date: str) -> tuple[str, str]:
    return (end_date, start_date) if start_date > end_date else (start_date, end_date)


def _encode_game_value(date: str, match_id: str) -> str:
    return f"{date}|{match_id}"


def _decode_game_value(value: str) -> tuple[str, str]:
    date, match_id = value.split("|", 1)
    return date, match_id


def _build_pregame_card(trades_df, data, manifest, analysis_summary=None):
    tip_off = None
    if data["events"]:
        for event in data["events"]:
            if event.get("time_actual_dt"):
                tip_off = event["time_actual_dt"]
                break

    away_token = manifest["token_ids"][0]
    away_team = manifest["outcomes"][0]

    opening_price = None
    opening_source = "unknown"
    opening_team = away_team
    if analysis_summary:
        opening_team = analysis_summary["open"]["team"] or away_team
        opening_price = analysis_summary["open"]["price"]
        opening_source = analysis_summary["open"]["source"] or "unknown"

    pregame = trades_df[trades_df["datetime"] < tip_off] if tip_off is not None else trades_df
    pregame_away = pregame[pregame["asset"] == away_token]
    last_pre_price = pregame_away.iloc[-1]["price"] if not pregame_away.empty else None
    drift = None
    if opening_price is not None and last_pre_price is not None:
        drift = last_pre_price - opening_price

    return [
        html.H4("Pre-Game Summary", style={"marginTop": 0}),
        info_row(
            f"Opening ({opening_team})",
            f"{opening_price:.3f} ({opening_source})" if opening_price is not None else "N/A",
        ),
        info_row(f"Last Pre-Tipoff ({away_team})", f"{last_pre_price:.3f}" if last_pre_price is not None else "N/A"),
        info_row("Drift", f"{drift:+.3f}" if drift is not None else "N/A"),
        info_row("Pre-Game Trades", f"{len(pregame):,}"),
        info_row("Pre-Game Volume", f"${pregame['size'].sum():,.0f}"),
    ]


def _build_analysis_card(summary: dict, price_quality_filter: str):
    open_data = summary["open"]
    tipoff_data = summary["tipoff"]

    def anchor_block(title, anchor):
        return html.Div(
            style={"padding": "10px 0", "borderTop": "1px solid #333"},
            children=[
                html.H5(title, style={"margin": "0 0 8px 0", "color": "#9ad1ff"}),
                info_row("Favorite", anchor["team"] or "N/A"),
                info_row("Price", format_prob(anchor["price"])),
                info_row("Source", anchor["source"] or "N/A"),
                info_row("Interpretable Band", anchor["interpretable_band"] or "N/A"),
                info_row("Quantile Band", anchor["quantile_band"] or "N/A"),
                info_row("Quantile Cutoffs", format_quantile_cutoffs(anchor["quantile_cutoffs"])),
            ],
        )

    return [
        html.H4("Game Analytics", style={"marginTop": 0}),
        info_row("Sport Slice", summary["sport"].upper()),
        info_row("Price Quality Filter", price_quality_filter),
        info_row("Comparison Games", f"{summary['population_games']:,}"),
        anchor_block("Market Open Regime", open_data),
        anchor_block("Tip-Off Regime", tipoff_data),
    ]


def _build_whale_card(whale_data: dict):
    summary = whale_data["summary"]
    whales = whale_data["whales"]

    if not whales:
        return html.Div(
            style=CARD_STYLE,
            children=[html.H4("Whale Tracker", style={"marginTop": 0}), html.P("No whales detected", style={"color": "#888"})],
        )

    badge_colors = {"Market Maker": "#4CAF50", "Directional": "#FF5722", "Hybrid": "#FFC107"}
    side_colors = {"BUY": "#4CAF50", "SELL": "#FF5722", "Mixed": "#FFC107", "N/A": "#888"}

    def position_tags(positions):
        if not positions:
            return html.Span("N/A", style={"color": "#888"})
        tags = []
        for position in positions:
            color = side_colors.get(position["net_side"], "#888")
            volume = position["buy_volume"] + position["sell_volume"]
            tags.append(
                html.Span(
                    f"{position['team']} {position['net_side']} ${volume:,.0f}",
                    style={"color": color, "fontSize": "11px", "marginRight": "8px", "whiteSpace": "nowrap"},
                )
            )
        return html.Span(tags)

    def side_summary(whale, mode: str):
        primary_side = whale.get("primary_side", "N/A")
        side_color = side_colors.get(primary_side, "#888")
        positions = whale.get("positions", [])

        if mode == "taker":
            label = "Bias"
            if whale.get("taker_volume", 0) <= 0:
                summary_text = "No taker trades"
                detail = html.Span("No directional data", style={"color": "#888"})
            else:
                summary_text = primary_side
                detail = position_tags(positions)
        else:
            label = "Flow"
            if whale.get("maker_volume", 0) <= 0:
                summary_text = "No maker trades"
                detail = html.Span("No passive flow", style={"color": "#888"})
            elif whale.get("taker_volume", 0) <= 0:
                summary_text = "Passive"
                detail = html.Span("Maker flow only, side not inferable", style={"color": "#888"})
            else:
                summary_text = f"Passive + {primary_side}"
                detail = position_tags(positions)

        return html.Div(
            style={"display": "flex", "flexDirection": "column", "minWidth": "220px"},
            children=[
                html.Span(
                    [html.Span(f"{label}: ", style={"color": "#888"}), html.Span(summary_text, style={"color": side_color, "fontWeight": "bold"})],
                    style={"fontSize": "12px"},
                ),
                html.Div(detail, style={"marginTop": "2px"}),
            ],
        )

    def trade_stats_block(whale, mode: str):
        stats = whale.get(f"{mode}_trade_stats", {})
        labels = [
            ("Trades", stats.get("count", 0), False),
            ("Min", stats.get("min", 0), True),
            ("Max", stats.get("max", 0), True),
            ("Mean", stats.get("mean", 0), True),
            ("Median", stats.get("median", 0), True),
        ]
        return html.Div(
            style={"display": "grid", "gridTemplateColumns": "repeat(4, minmax(72px, 1fr))", "gap": "6px", "minWidth": "320px"},
            children=[
                html.Div(
                    style={"display": "flex", "flexDirection": "column", "textAlign": "right"},
                    children=[
                        html.Span(label, style={"fontSize": "11px", "color": "#888"}),
                        html.Span(f"{value:,}" if not is_currency else f"${value:,.0f}", style={"fontWeight": "bold"}),
                    ],
                )
                for label, value, is_currency in labels
            ],
        )

    def whale_row(whale, mode: str, volume_key: str, volume_label: str, rank: int | None = None):
        badge_color = badge_colors.get(whale["classification"], "#888")
        rank_label = f"#{rank}" if rank is not None else None
        return html.Div(
            style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "padding": "4px 0", "borderBottom": "1px solid #333", "fontSize": "13px", "gap": "8px"},
            children=[
                html.Span(rank_label or "", style={"minWidth": "34px", "fontWeight": "bold", "color": "#bbb", "textAlign": "right"}),
                html.Span(whale["display_addr"], style={"fontFamily": "monospace", "minWidth": "120px"}),
                html.Div(
                    style={"display": "flex", "flexDirection": "column", "minWidth": "110px", "textAlign": "right"},
                    children=[
                        html.Span(f"${whale[volume_key]:,.0f}", style={"fontWeight": "bold"}),
                        html.Span(volume_label, style={"fontSize": "11px", "color": "#888"}),
                    ],
                ),
                html.Span(f"${whale['total_volume']:,.0f} total", style={"minWidth": "90px", "textAlign": "right"}),
                html.Span(f"{whale['pct_of_total']:.1f}%", style={"minWidth": "50px", "textAlign": "right"}),
                html.Span(
                    whale["classification"],
                    style={"backgroundColor": badge_color, "color": "#111", "padding": "2px 6px", "borderRadius": "4px", "fontSize": "11px", "fontWeight": "bold", "minWidth": "90px", "textAlign": "center"},
                ),
                trade_stats_block(whale, mode),
                side_summary(whale, mode),
            ],
        )

    by_taker = sorted(
        [whale for whale in whales if whale["taker_volume"] > 0 and whale["classification"] != "Market Maker"],
        key=lambda whale: whale["taker_volume"],
        reverse=True,
    )[:10]
    by_maker = sorted([whale for whale in whales if whale["maker_volume"] > 0], key=lambda whale: whale["maker_volume"], reverse=True)[:5]

    return html.Div(
        style=CARD_STYLE,
        children=[
            html.H4("Whale Tracker", style={"marginTop": 0}),
            html.P(
                f"{summary['whale_count']} whales = ${summary['whale_volume']:,.0f} ({summary['whale_pct']:.1f}% of volume)",
                style={"color": "#FFD600", "fontWeight": "bold", "marginBottom": "12px"},
            ),
            html.Div(
                style={"display": "flex", "flexDirection": "column", "gap": "16px"},
                children=[
                    html.Div(
                        style={"width": "100%", "padding": "12px 14px", "backgroundColor": "#141422", "borderRadius": "8px"},
                        children=[html.H5("Top Aggressors (Takers)", style={"color": "#FF5722", "marginTop": 0})]
                        + [whale_row(whale, "taker", "taker_volume", "Aggressor Vol", rank=index) for index, whale in enumerate(by_taker, start=1)],
                    ),
                    html.Div(
                        style={"width": "100%", "padding": "12px 14px", "backgroundColor": "#141422", "borderRadius": "8px"},
                        children=[html.H5("Top Liquidity (Makers)", style={"color": "#4CAF50", "marginTop": 0})]
                        + [whale_row(whale, "maker", "maker_volume", "Maker Vol") for whale in by_maker],
                    ),
                ],
            ),
        ],
    )
