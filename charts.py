"""Plotly chart builders for NBA game visualization."""

from datetime import timedelta

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
    settings: dict | None = None,
    whale_addresses: set[str] | None = None,
) -> tuple[go.Figure, go.Figure | None]:
    """Build pre-game and in-game chart figures.

    Returns (pregame_fig, game_fig). game_fig is None if no tip-off found.
    """
    settings = settings or {}
    spike_cfg = (
        settings.get("vol_spike_std", 2.0),
        settings.get("vol_spike_lookback", 20),
    )
    pregame_min_cum_vol = settings.get("pregame_min_cum_vol", 5000)
    post_game_buffer = timedelta(minutes=settings.get("post_game_buffer_min", 10))

    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]
    away_token = manifest["token_ids"][0]
    home_token = manifest["token_ids"][1]

    tip_off = _get_tipoff(events)

    if tip_off is None:
        fig = _build_subplot_figure(
            trades_df, away_token, home_token, away_team, home_team,
            title="All Trades (no tip-off detected)",
            vmarkers=_collect_vmarkers(gamma_start, None, gamma_closed),
            events=None, tricode_map=tricode_map, spike_cfg=spike_cfg,
            whale_addresses=whale_addresses,
        )
        return fig, None

    # Split trades at tip-off
    pre_trades = trades_df[trades_df["datetime"] < tip_off]
    game_trades = trades_df[trades_df["datetime"] >= tip_off]

    # Filter pre-game: drop early low-activity trades
    pre_trades = _filter_by_min_cum_vol(pre_trades, pregame_min_cum_vol)

    # Determine game end from last event + buffer
    game_end = _get_game_end(events)
    if game_end is not None:
        cutoff = game_end + post_game_buffer
        game_trades = game_trades[game_trades["datetime"] <= cutoff]

    pre_vmarkers = _collect_vmarkers(gamma_start, tip_off, None)
    pregame_fig = _build_subplot_figure(
        pre_trades, away_token, home_token, away_team, home_team,
        title="Pre-Game",
        vmarkers=pre_vmarkers,
        events=None, tricode_map=tricode_map, spike_cfg=spike_cfg,
        whale_addresses=whale_addresses,
    )

    # Only include market close marker if it falls within the clipped range
    effective_closed = gamma_closed
    if game_end is not None and gamma_closed is not None and gamma_closed > cutoff:
        effective_closed = None
    game_vmarkers = _collect_vmarkers(None, tip_off, effective_closed)
    if game_end is not None:
        game_vmarkers.append((game_end, "#00E676", "dot", "Game End"))
    game_fig = _build_subplot_figure(
        game_trades, away_token, home_token, away_team, home_team,
        title="In-Game",
        vmarkers=game_vmarkers,
        events=events, tricode_map=tricode_map, spike_cfg=spike_cfg,
        whale_addresses=whale_addresses,
    )

    return pregame_fig, game_fig


def _filter_by_min_cum_vol(trades_df: pd.DataFrame, min_vol: float) -> pd.DataFrame:
    """Drop trades before cumulative volume first reaches min_vol."""
    if trades_df.empty or min_vol <= 0:
        return trades_df
    sorted_df = trades_df.sort_values("datetime")
    cum = sorted_df["size"].cumsum()
    mask = cum >= min_vol
    if not mask.any():
        return trades_df  # never reaches threshold — keep all
    return sorted_df.loc[mask]


def _build_subplot_figure(
    trades_df, away_token, home_token, away_team, home_team,
    title, vmarkers, events, tricode_map, spike_cfg=(2.0, 20),
    whale_addresses=None,
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

    away_label = f"{away_team} (Away)"
    home_label = f"{home_team} (Home)"

    fig.add_trace(
        go.Scattergl(
            x=away_trades["datetime"], y=away_trades["price"],
            mode="lines", name=away_label,
            line=dict(color="#1f77b4", width=1.5),
            hovertemplate="%{x}<br>Price: %{y:.3f}<extra>" + away_label + "</extra>",
            legend="legend",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scattergl(
            x=home_trades["datetime"], y=home_trades["price"],
            mode="lines", name=home_label,
            line=dict(color="#ff7f0e", width=1.5),
            hovertemplate="%{x}<br>Price: %{y:.3f}<extra>" + home_label + "</extra>",
            legend="legend",
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

    # Row 2: Volume bars (4-way: away buy/sell, home buy/sell)
    _add_volume_bars(fig, trades_df, away_token, home_token, away_team, home_team)

    # Volume spike markers
    std_mult, lookback = spike_cfg
    _mark_volume_spikes(fig, trades_df, std_mult, lookback)

    # Whale volume overlay
    if whale_addresses:
        _add_whale_volume_line(fig, trades_df, whale_addresses)

    # Row 3: Cumulative volume (4 lines: away buy/sell, home buy/sell)
    _add_cumulative_lines(fig, trades_df, away_token, home_token, away_team, home_team)

    fig.update_layout(
        height=700,
        template="plotly_dark",
        showlegend=True,
        # Price legend — above row 1
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1, font=dict(size=11)),
        # Volume legend — above row 2
        legend2=dict(orientation="h", yanchor="bottom", y=0.44,
                     xanchor="right", x=1, font=dict(size=10)),
        # Cumulative legend — above row 3
        legend3=dict(orientation="h", yanchor="bottom", y=0.19,
                     xanchor="right", x=1, font=dict(size=10)),
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


def _get_game_end(events: list[dict] | None):
    """Return last event's time_actual as game end."""
    if not events:
        return None
    for ev in reversed(events):
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


def _add_volume_bars(fig, trades_df: pd.DataFrame,
                     away_token: str, home_token: str,
                     away_team: str, home_team: str):
    """Add stacked volume bars to Row 2: away buy/sell + home buy/sell."""
    sorted_df = trades_df.sort_values("datetime")

    span = (sorted_df["datetime"].max() - sorted_df["datetime"].min()).total_seconds()
    freq = "1min" if span < 6 * 3600 else "5min"

    # (token, side, color, label)
    combos = [
        (away_token, "BUY",  "#2196F3", f"{away_team} Buy"),
        (away_token, "SELL", "#0D47A1", f"{away_team} Sell"),
        (home_token, "BUY",  "#FF9800", f"{home_team} Buy"),
        (home_token, "SELL", "#E65100", f"{home_team} Sell"),
    ]

    for token, side, color, label in combos:
        subset = sorted_df[(sorted_df["asset"] == token) & (sorted_df["side"] == side)].copy()
        if subset.empty:
            continue
        subset = subset.set_index("datetime")
        bucketed = subset["size"].resample(freq).sum().fillna(0)

        fig.add_trace(
            go.Bar(
                x=bucketed.index, y=bucketed.values,
                name=label, marker_color=color,
                hovertemplate="%{x}<br>$%{y:,.0f}<extra>" + label + "</extra>",
                legend="legend2",
            ),
            row=2, col=1,
        )


def _mark_volume_spikes(fig, trades_df: pd.DataFrame,
                        std_mult: float, lookback: int):
    """Add triangle markers above volume bars that exceed rolling mean + N*std."""
    sorted_df = trades_df.sort_values("datetime")
    if sorted_df.empty:
        return

    span = (sorted_df["datetime"].max() - sorted_df["datetime"].min()).total_seconds()
    freq = "1min" if span < 6 * 3600 else "5min"

    # Total volume per bucket (across all teams/sides)
    bucketed = sorted_df.set_index("datetime")["size"].resample(freq).sum().fillna(0)

    if len(bucketed) < lookback:
        return

    rolling_mean = bucketed.rolling(lookback, min_periods=1).mean()
    rolling_std = bucketed.rolling(lookback, min_periods=1).std().fillna(0)
    threshold = rolling_mean + std_mult * rolling_std

    spikes = bucketed[bucketed > threshold]

    if spikes.empty:
        return

    fig.add_trace(
        go.Scatter(
            x=spikes.index, y=spikes.values,
            mode="markers",
            marker=dict(size=10, color="#FFD600", symbol="triangle-up",
                        line=dict(width=1, color="#FF6F00")),
            name=f"Vol Spike (>{std_mult:.0f}\u03c3)",
            text=[f"${v:,.0f} (thresh: ${t:,.0f})"
                  for v, t in zip(spikes.values, threshold.loc[spikes.index].values)],
            hovertemplate="%{x}<br>%{text}<extra>Volume Spike</extra>",
            legend="legend2",
        ),
        row=2, col=1,
    )


def _add_whale_volume_line(fig, trades_df: pd.DataFrame, whale_addresses: set[str]):
    """Add whale volume scatter fill overlay to Row 2."""
    sorted_df = trades_df.sort_values("datetime")
    if sorted_df.empty:
        return

    span = (sorted_df["datetime"].max() - sorted_df["datetime"].min()).total_seconds()
    freq = "1min" if span < 6 * 3600 else "5min"

    # Filter to trades involving whale wallets
    whale_mask = sorted_df["maker"].isin(whale_addresses) | sorted_df["taker"].isin(whale_addresses)
    whale_trades = sorted_df[whale_mask]
    if whale_trades.empty:
        return

    # Bucket whale volume
    whale_bucketed = whale_trades.set_index("datetime")["size"].resample(freq).sum().fillna(0)

    # Bucket total volume for hover pct
    total_bucketed = sorted_df.set_index("datetime")["size"].resample(freq).sum().fillna(0)

    # Align indices
    whale_bucketed = whale_bucketed.reindex(total_bucketed.index, fill_value=0)

    pct_text = [
        f"${wv:,.0f} ({wv / tv * 100:.0f}%)" if tv > 0 else "$0"
        for wv, tv in zip(whale_bucketed.values, total_bucketed.values)
    ]

    fig.add_trace(
        go.Scatter(
            x=whale_bucketed.index, y=whale_bucketed.values,
            mode="lines", fill="tozeroy",
            line=dict(color="#FFD600", width=1),
            fillcolor="rgba(255, 214, 0, 0.15)",
            name="Whale Vol",
            text=pct_text,
            hovertemplate="%{x}<br>%{text}<extra>Whale Vol</extra>",
            legend="legend2",
        ),
        row=2, col=1,
    )


def _add_cumulative_lines(fig, trades_df: pd.DataFrame,
                          away_token: str, home_token: str,
                          away_team: str, home_team: str):
    """Add 4 cumulative volume lines to Row 3."""
    sorted_df = trades_df.sort_values("datetime")

    combos = [
        (away_token, "BUY",  "#2196F3", f"{away_team} Cum Buy"),
        (away_token, "SELL", "#0D47A1", f"{away_team} Cum Sell"),
        (home_token, "BUY",  "#FF9800", f"{home_team} Cum Buy"),
        (home_token, "SELL", "#E65100", f"{home_team} Cum Sell"),
    ]

    for token, side, color, label in combos:
        subset = sorted_df[(sorted_df["asset"] == token) & (sorted_df["side"] == side)]
        if subset.empty:
            continue
        cum = subset["size"].cumsum()
        fig.add_trace(
            go.Scattergl(
                x=subset["datetime"], y=cum,
                mode="lines", name=label,
                line=dict(color=color, width=1.5),
                hovertemplate="%{x}<br>$%{y:,.0f}<extra>" + label + "</extra>",
                legend="legend3",
            ),
            row=3, col=1,
        )
