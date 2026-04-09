"""Plotly chart builders for NBA game visualization."""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def build_charts(
    trades_df: pd.DataFrame,
    manifest: dict,
    events: list[dict] | None,
    tricode_map: dict,
    gamma_start=None,
    gamma_closed=None,
) -> tuple[go.Figure, go.Figure | None]:
    """Build pre-game and in-game chart figures.

    Returns (pregame_fig, game_fig). game_fig is None if no tip-off found.
    """
    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]
    away_token = manifest["token_ids"][0]
    home_token = manifest["token_ids"][1]

    tip_off = _get_tipoff(events)

    if tip_off is None:
        # No tip-off — single chart with all trades
        fig = _build_subplot_figure(
            trades_df, away_token, home_token, away_team, home_team,
            title="All Trades (no tip-off detected)",
            vmarkers=_collect_vmarkers(gamma_start, None, gamma_closed),
            events=None, tricode_map=tricode_map,
        )
        return fig, None

    # Split trades at tip-off
    pre_trades = trades_df[trades_df["datetime"] < tip_off]
    game_trades = trades_df[trades_df["datetime"] >= tip_off]

    # Pre-game figure
    pre_vmarkers = _collect_vmarkers(gamma_start, tip_off, None)
    pregame_fig = _build_subplot_figure(
        pre_trades, away_token, home_token, away_team, home_team,
        title="Pre-Game",
        vmarkers=pre_vmarkers,
        events=None, tricode_map=tricode_map,
    )

    # In-game figure
    game_vmarkers = _collect_vmarkers(None, tip_off, gamma_closed)
    game_fig = _build_subplot_figure(
        game_trades, away_token, home_token, away_team, home_team,
        title="In-Game",
        vmarkers=game_vmarkers,
        events=events, tricode_map=tricode_map,
    )

    return pregame_fig, game_fig


def _build_subplot_figure(
    trades_df, away_token, home_token, away_team, home_team,
    title, vmarkers, events, tricode_map,
) -> go.Figure:
    """Build a 3-row subplot figure for a slice of trades."""
    if trades_df.empty:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark", height=300,
            annotations=[dict(text=f"{title}: no trades", showarrow=False,
                              xref="paper", yref="paper", x=0.5, y=0.5,
                              font=dict(size=18, color="#888"))],
        )
        return fig

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.55, 0.25, 0.20],
        subplot_titles=(f"{title} — Price", "Volume", "Cumulative Volume"),
    )

    # Row 1: Price lines
    away_trades = trades_df[trades_df["asset"] == away_token].sort_values("datetime")
    home_trades = trades_df[trades_df["asset"] == home_token].sort_values("datetime")

    fig.add_trace(
        go.Scattergl(
            x=away_trades["datetime"], y=away_trades["price"],
            mode="lines", name=away_team,
            line=dict(color="#1f77b4", width=1.5),
            hovertemplate="%{x}<br>Price: %{y:.3f}<extra>" + away_team + "</extra>",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scattergl(
            x=home_trades["datetime"], y=home_trades["price"],
            mode="lines", name=home_team,
            line=dict(color="#ff7f0e", width=1.5),
            hovertemplate="%{x}<br>Price: %{y:.3f}<extra>" + home_team + "</extra>",
        ),
        row=1, col=1,
    )

    # Vertical markers on price row
    _add_vertical_markers(fig, vmarkers)

    # Event markers
    if events:
        _add_event_markers(
            fig, events, tricode_map, away_trades, home_trades,
            away_team, home_team,
        )

    # Row 2: Volume bars
    _add_volume_bars(fig, trades_df)

    # Row 3: Cumulative volume
    sorted_trades = trades_df.sort_values("datetime")
    cum_size = sorted_trades["size"].cumsum()
    fig.add_trace(
        go.Scattergl(
            x=sorted_trades["datetime"], y=cum_size,
            mode="lines", name="Cumulative Vol",
            line=dict(color="#9467bd", width=1.5),
            hovertemplate="%{x}<br>Cumulative: $%{y:,.0f}<extra></extra>",
        ),
        row=3, col=1,
    )

    fig.update_layout(
        height=700,
        template="plotly_dark",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=30, t=40, b=40),
        xaxis3=dict(rangeslider=dict(visible=True, thickness=0.05)),
        hovermode="x unified",
        barmode="stack",
    )

    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume ($)", row=2, col=1)
    fig.update_yaxes(title_text="Cumulative ($)", row=3, col=1)

    return fig


# --- Helpers ---

def _get_tipoff(events: list[dict] | None):
    """Return tip-off datetime (first event's time_actual)."""
    if not events:
        return None
    for ev in events:
        dt = ev.get("time_actual_dt")
        if dt is not None:
            return dt
    return None


def _collect_vmarkers(gamma_start, tip_off, gamma_closed) -> list[tuple]:
    """Build list of (timestamp, color, dash, label) vertical markers."""
    markers = []
    if gamma_start:
        markers.append((gamma_start, "gray", "dash", "Scheduled Start"))
    if tip_off:
        markers.append((tip_off, "green", "solid", "Tip-Off"))
    if gamma_closed:
        markers.append((gamma_closed, "red", "dash", "Market Close"))
    return markers


def _add_vertical_markers(fig, markers: list[tuple]):
    """Add vertical reference lines to Row 1."""
    for ts, color, dash, label in markers:
        fig.add_shape(
            type="line", x0=ts, x1=ts, y0=0, y1=1,
            yref="y domain", xref="x",
            line=dict(color=color, width=1.5 if dash == "solid" else 1, dash=dash),
            row=1, col=1,
        )
        fig.add_annotation(
            x=ts, y=1, yref="y domain", xref="x",
            text=label, showarrow=False,
            font=dict(size=10, color=color),
            yshift=10,
            row=1, col=1,
        )


def _add_event_markers(
    fig, events, tricode_map, away_trades, home_trades,
    away_team, home_team,
):
    """Add scoring event scatter markers on price lines."""
    scoring_types = {"2pt", "3pt", "freethrow"}

    for team_name, team_trades, color in [
        (away_team, away_trades, "#1f77b4"),
        (home_team, home_trades, "#ff7f0e"),
    ]:
        team_tricodes = {tc for tc, name in tricode_map.items() if name == team_name}
        team_events = [
            ev for ev in events
            if ev.get("team_tricode") in team_tricodes
            and ev.get("event_type") in scoring_types
            and ev.get("time_actual_dt") is not None
        ]

        if not team_events or team_trades.empty:
            continue

        xs, ys, hovers = [], [], []
        for ev in team_events:
            t = ev["time_actual_dt"]
            y = _nearest_price(team_trades, t)
            if y is None:
                continue
            score = f"{ev.get('away_score', '?')}-{ev.get('home_score', '?')}"
            hover = f"{score} | {ev.get('event_type', '')} | {ev.get('description', '')}"
            xs.append(t)
            ys.append(y)
            hovers.append(hover)

        if xs:
            fig.add_trace(
                go.Scatter(
                    x=xs, y=ys, mode="markers",
                    marker=dict(size=7, color=color, symbol="circle",
                                line=dict(width=1, color="white")),
                    name=f"{team_name} scores",
                    text=hovers,
                    hovertemplate="%{text}<extra></extra>",
                    showlegend=False,
                ),
                row=1, col=1,
            )


def _nearest_price(team_trades: pd.DataFrame, t, max_gap_s: int = 60) -> float | None:
    """Find the nearest trade price to timestamp t."""
    if team_trades.empty:
        return None

    diffs = (team_trades["datetime"] - t).abs()
    idx = diffs.idxmin()
    gap = diffs.loc[idx].total_seconds()

    if gap <= max_gap_s:
        return team_trades.loc[idx, "price"]

    before = team_trades[team_trades["datetime"] <= t]
    if not before.empty:
        return before.iloc[-1]["price"]

    return None


def _add_volume_bars(fig, trades_df: pd.DataFrame):
    """Add stacked BUY/SELL volume bars to Row 2."""
    sorted_df = trades_df.sort_values("datetime")

    span = (sorted_df["datetime"].max() - sorted_df["datetime"].min()).total_seconds()
    freq = "1min" if span < 6 * 3600 else "5min"

    for side, color, label in [("BUY", "#2ca02c", "Buy Vol"), ("SELL", "#d62728", "Sell Vol")]:
        side_df = sorted_df[sorted_df["side"] == side].copy()
        if side_df.empty:
            continue
        side_df = side_df.set_index("datetime")
        bucketed = side_df["size"].resample(freq).sum().fillna(0)

        fig.add_trace(
            go.Bar(
                x=bucketed.index, y=bucketed.values,
                name=label, marker_color=color,
                hovertemplate="%{x}<br>$%{y:,.0f}<extra>" + label + "</extra>",
            ),
            row=2, col=1,
        )
