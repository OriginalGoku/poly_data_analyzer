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
    top_taker_whales: list[dict] | None = None,
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
    whale_marker_min_trade_pct = settings.get("whale_marker_min_trade_pct", 0.25)

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
            top_taker_whales=None,
            whale_marker_min_trade_pct=whale_marker_min_trade_pct,
            discrete_price_points=True,
        )
        return fig, None

    # Split trades at tip-off. Preserve cumulative history before filtering so
    # pregame cumulative traces do not visually reset after the threshold gate.
    pre_trades = trades_df[trades_df["datetime"] < tip_off].sort_values("datetime").copy()
    if not pre_trades.empty:
        pre_trades["global_cum_size"] = pre_trades["size"].cumsum()
        pre_trades["asset_side_cum_size"] = (
            pre_trades.groupby(["asset", "side"], sort=False)["size"].cumsum()
        )
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
        top_taker_whales=None,
        whale_marker_min_trade_pct=whale_marker_min_trade_pct,
        discrete_price_points=True,
    )

    # Only include market close marker if it falls within the clipped range
    effective_closed = gamma_closed
    if game_end is not None and gamma_closed is not None and gamma_closed > cutoff:
        effective_closed = None
    game_vmarkers = _collect_vmarkers(None, tip_off, effective_closed)
    if game_end is not None:
        game_vmarkers.append((game_end, "#00E676", "dot", "Game End"))
    score_lead_label = _format_score_lead_label(away_team, home_team, events)
    game_title = f"In-Game — {away_team} @ {home_team}"
    if score_lead_label:
        game_title += f" | {score_lead_label}"
    game_fig = _build_subplot_figure(
        game_trades, away_token, home_token, away_team, home_team,
        title=game_title,
        vmarkers=game_vmarkers,
        events=events, tricode_map=tricode_map, spike_cfg=spike_cfg,
        whale_addresses=whale_addresses,
        top_taker_whales=top_taker_whales,
        whale_marker_min_trade_pct=whale_marker_min_trade_pct,
        discrete_price_points=False,
    )

    return pregame_fig, game_fig


def build_score_chart(
    manifest: dict,
    events: list[dict] | None,
    title: str = "In-Game Score Progression",
) -> go.Figure:
    """Build a simple score progression chart from play-by-play events."""
    if not events:
        return _empty_score_figure(f"{title}: no events available")

    score_events = [
        ev for ev in events
        if ev.get("time_actual_dt") is not None
        and ev.get("away_score") is not None
        and ev.get("home_score") is not None
    ]
    if not score_events:
        return _empty_score_figure(f"{title}: no score events available")

    score_df = pd.DataFrame(
        {
            "datetime": [ev["time_actual_dt"] for ev in score_events],
            "away_score": [ev.get("away_score", 0) or 0 for ev in score_events],
            "home_score": [ev.get("home_score", 0) or 0 for ev in score_events],
            "event_type": [ev.get("event_type", "") for ev in score_events],
            "description": [ev.get("description", "") for ev in score_events],
        }
    ).sort_values("datetime")

    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=score_df["datetime"],
            y=score_df["away_score"],
            mode="lines+markers",
            line=dict(shape="hv", color="#1f77b4", width=2),
            marker=dict(size=5),
            name=f"{away_team} Score",
            customdata=score_df[["event_type", "description"]].values,
            hovertemplate=(
                "%{x}<br>"
                f"{away_team}: "
                "%{y}<br>"
                "Event: %{customdata[0]}<br>"
                "%{customdata[1]}"
                "<extra></extra>"
            ),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=score_df["datetime"],
            y=score_df["home_score"],
            mode="lines+markers",
            line=dict(shape="hv", color="#ff7f0e", width=2),
            marker=dict(size=5),
            name=f"{home_team} Score",
            customdata=score_df[["event_type", "description"]].values,
            hovertemplate=(
                "%{x}<br>"
                f"{home_team}: "
                "%{y}<br>"
                "Event: %{customdata[0]}<br>"
                "%{customdata[1]}"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        template="plotly_dark",
        title=title,
        height=340,
        margin=dict(l=60, r=30, t=50, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Score")
    fig.update_xaxes(title_text="Time")
    return fig


def build_score_diff_chart(
    manifest: dict,
    events: list[dict] | None,
    title: str = "Score Difference",
) -> go.Figure:
    """Build a bar chart showing the current lead at each score event."""
    if not events:
        return _empty_score_figure(f"{title}: no events available", height=260)

    score_events = [
        ev for ev in events
        if ev.get("time_actual_dt") is not None
        and ev.get("away_score") is not None
        and ev.get("home_score") is not None
    ]
    if not score_events:
        return _empty_score_figure(f"{title}: no score events available", height=260)

    score_df = pd.DataFrame(
        {
            "datetime": [ev["time_actual_dt"] for ev in score_events],
            "away_score": [ev.get("away_score", 0) or 0 for ev in score_events],
            "home_score": [ev.get("home_score", 0) or 0 for ev in score_events],
            "event_type": [ev.get("event_type", "") for ev in score_events],
            "description": [ev.get("description", "") for ev in score_events],
        }
    ).sort_values("datetime")

    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]
    away_color = "#1f77b4"
    home_color = "#ff7f0e"
    tied_color = "#888888"

    score_df["lead_diff"] = (score_df["away_score"] - score_df["home_score"]).abs()
    score_df["leader"] = score_df.apply(
        lambda row: away_team if row["away_score"] > row["home_score"]
        else home_team if row["home_score"] > row["away_score"]
        else "Tied",
        axis=1,
    )
    score_df["color"] = score_df["leader"].map(
        {away_team: away_color, home_team: home_color, "Tied": tied_color}
    )

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=score_df["datetime"],
            y=score_df["lead_diff"],
            marker=dict(color=score_df["color"]),
            customdata=score_df[["leader", "away_score", "home_score", "event_type", "description"]].values,
            hovertemplate=(
                "%{x}<br>"
                "Leader: %{customdata[0]}<br>"
                "Lead: %{y}<br>"
                f"{away_team}: "
                "%{customdata[1]}<br>"
                f"{home_team}: "
                "%{customdata[2]}<br>"
                "Event: %{customdata[3]}<br>"
                "%{customdata[4]}"
                "<extra></extra>"
            ),
            name="Lead",
            showlegend=False,
        )
    )
    fig.update_layout(
        template="plotly_dark",
        title=title,
        height=260,
        margin=dict(l=60, r=30, t=45, b=40),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Lead")
    fig.update_xaxes(title_text="Time")
    return fig


def build_sensitivity_timeline(
    sensitivity_df: pd.DataFrame | None,
    manifest: dict,
    events: list[dict] | None,
    title: str = "Price Sensitivity to Scoring",
) -> go.Figure:
    """Build a per-event delta-price scatter over game time."""
    if sensitivity_df is None or sensitivity_df.empty:
        return _empty_score_figure(f"{title}: no sensitivity data available")

    plotted = sensitivity_df.dropna(subset=["delta_price"]).copy()
    if plotted.empty:
        return _empty_score_figure(f"{title}: no valid event-price pairs")

    away_team = manifest["outcomes"][0]
    home_team = manifest["outcomes"][1]
    away_label = f"{away_team} (Away)"
    home_label = f"{home_team} (Home)"
    team_colors = {away_team: "#1f77b4", home_team: "#ff7f0e"}
    point_sizes = {1: 6, 2: 10, 3: 14}
    window_estimate = max(
        int(plotted["trades_before_count"].max()),
        int(plotted["trades_after_count"].max()),
    )

    fig = go.Figure()
    for team, label in [(away_team, away_label), (home_team, home_label)]:
        team_df = plotted[plotted["team"] == team]
        if team_df.empty:
            continue
        opacities = [
            0.6 if before < window_estimate or after < window_estimate else 0.95
            for before, after in zip(
                team_df["trades_before_count"],
                team_df["trades_after_count"],
            )
        ]
        fig.add_trace(
            go.Scatter(
                x=team_df["event_time"],
                y=team_df["delta_price"],
                mode="markers",
                name=label,
                marker=dict(
                    color=team_colors.get(team, "#888"),
                    size=[point_sizes.get(points, 8) for points in team_df["points"]],
                    opacity=opacities,
                    line=dict(width=1, color="#111"),
                ),
                customdata=team_df[
                    [
                        "points",
                        "period",
                        "pre_lead",
                        "post_lead",
                        "trades_before_count",
                        "trades_after_count",
                        "pre_leader",
                        "post_leader",
                    ]
                ].values,
                hovertemplate=(
                    "%{x}<br>"
                    "Team: " + label + "<br>"
                    "Points: %{customdata[0]}<br>"
                    "Period: %{customdata[1]}<br>"
                    "Score gap: %{customdata[2]} → %{customdata[3]}<br>"
                    "Leader: %{customdata[6]} → %{customdata[7]}<br>"
                    "ΔPrice: %{y:+.4g}<br>"
                    "Trades used: %{customdata[4]} before / %{customdata[5]} after"
                    "<extra></extra>"
                ),
            )
        )

    fig.add_hline(y=0, line_color="#888", line_width=1, line_dash="dot")
    _add_period_boundaries(fig, events, plotted["period"].max())
    fig.update_layout(
        template="plotly_dark",
        title=title,
        height=340,
        margin=dict(l=60, r=30, t=50, b=40),
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="ΔPrice (Away Token)")
    fig.update_xaxes(title_text="Time")
    return fig


def build_sensitivity_surface(
    sensitivity_df: pd.DataFrame | None,
    manifest: dict,
    settings,
    title: str = "Sensitivity by Game Phase & Score Gap",
) -> go.Figure:
    """Build quarter- and time-bucketed sensitivity summary bars."""
    if sensitivity_df is None or sensitivity_df.empty:
        return _empty_score_figure(f"{title}: no sensitivity data available", height=500)

    plotted = sensitivity_df.dropna(subset=["delta_price"]).copy()
    if plotted.empty:
        return _empty_score_figure(f"{title}: no valid event-price pairs", height=500)

    plotted["abs_delta_price"] = plotted["delta_price"].abs()
    window = int(getattr(settings, "sensitivity_price_window_trades", 5))
    plotted["low_confidence"] = (
        (plotted["trades_before_count"] < window)
        | (plotted["trades_after_count"] < window)
    )

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=False,
        vertical_spacing=0.16,
        subplot_titles=("By Quarter", "By Time Bucket"),
    )

    lead_bins = ["Close", "Moderate", "Blowout"]
    colors = {
        "Close": "#4CAF50",
        "Moderate": "#FFC107",
        "Blowout": "#EF5350",
    }

    quarter_grouped = _group_sensitivity(plotted, "period")
    for lead_bin in lead_bins:
        subset = quarter_grouped[quarter_grouped["lead_bin"] == lead_bin].sort_values("period")
        if subset.empty:
            continue
        fig.add_trace(
            go.Bar(
                x=[_period_label(period) for period in subset["period"]],
                y=subset["mean_abs_delta"],
                name=lead_bin,
                marker=dict(
                    color=colors[lead_bin],
                    opacity=[0.65 if low else 0.95 for low in subset["low_confidence"]],
                ),
                customdata=subset[["event_count", "median_delta"]].values,
                hovertemplate=(
                    "%{x}<br>"
                    f"Score Gap Bin: {lead_bin}<br>"
                    "Mean |ΔPrice|: %{y:.3f}<br>"
                    "Events: %{customdata[0]}<br>"
                    "Median ΔPrice: %{customdata[1]:+.3f}"
                    "<extra></extra>"
                ),
                legendgroup=lead_bin,
                showlegend=True,
            ),
            row=1,
            col=1,
        )

    time_grouped = _group_sensitivity(plotted, "time_bin")
    for lead_bin in lead_bins:
        subset = time_grouped[time_grouped["lead_bin"] == lead_bin].sort_values("time_bin")
        if subset.empty:
            continue
        fig.add_trace(
            go.Bar(
                x=[_time_bucket_label(bucket) for bucket in subset["time_bin"]],
                y=subset["mean_abs_delta"],
                name=lead_bin,
                marker=dict(
                    color=colors[lead_bin],
                    opacity=[0.65 if low else 0.95 for low in subset["low_confidence"]],
                ),
                customdata=subset[["event_count", "median_delta"]].values,
                hovertemplate=(
                    "%{x}<br>"
                    f"Score Gap Bin: {lead_bin}<br>"
                    "Mean |ΔPrice|: %{y:.3f}<br>"
                    "Events: %{customdata[0]}<br>"
                    "Median ΔPrice: %{customdata[1]:+.3f}"
                    "<extra></extra>"
                ),
                legendgroup=lead_bin,
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    fig.update_layout(
        template="plotly_dark",
        title=title,
        height=500,
        margin=dict(l=60, r=30, t=60, b=40),
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Mean |ΔPrice|", row=1, col=1)
    fig.update_yaxes(title_text="Mean |ΔPrice|", row=2, col=1)
    fig.update_xaxes(title_text="Quarter", row=1, col=1)
    fig.update_xaxes(title_text="Minutes Since Tipoff", row=2, col=1)
    return fig


def build_discrepancy_intervals_chart(
    discrepancy_df: pd.DataFrame | None,
    manifest: dict,
    title: str = "Market-Score Discrepancies",
) -> go.Figure:
    """Build a horizontal interval chart for market-score discrepancy spans."""
    if discrepancy_df is None or discrepancy_df.empty:
        return _empty_score_figure(f"{title}: no discrepancy intervals", height=360)

    plotted = discrepancy_df.sort_values("start_time").copy()
    plotted["label"] = [f"D{i}" for i in range(1, len(plotted) + 1)]
    plotted["duration_min"] = plotted["duration_seconds"] / 60.0
    plotted["flip_display"] = plotted.get("flip_flag", pd.Series(dtype=object)).map(
        lambda value: "Yes" if value else "No"
    )
    plotted["time_to_flip_display"] = plotted.get(
        "time_to_flip_seconds", pd.Series(dtype=float)
    ).map(lambda value: "N/A" if pd.isna(value) else f"{value:.1f}s")
    plotted["dead_zone_display"] = plotted.get(
        "returned_to_dead_zone", pd.Series(dtype=object)
    ).map(lambda value: "Yes" if value else "No")
    plotted["time_to_dead_zone_display"] = plotted.get(
        "time_to_dead_zone_seconds", pd.Series(dtype=float)
    ).map(lambda value: "N/A" if pd.isna(value) else f"{value:.1f}s")

    fig = go.Figure()
    lead_df = plotted[plotted["interval_type"] == "lead"].copy()
    tie_df = plotted[plotted["interval_type"] == "tie"].copy()
    if not lead_df.empty:
        fig.add_trace(
            go.Bar(
                x=lead_df["duration_min"],
                y=lead_df["label"],
                orientation="h",
                base=lead_df["start_time"],
                marker=dict(
                    color=lead_df["avg_discrepancy"],
                    colorscale="YlOrRd",
                    colorbar=dict(title="Avg Discrepancy"),
                    line=dict(color="#222", width=1),
                ),
                customdata=lead_df[
                    [
                        "start_time",
                        "end_time",
                        "trade_count",
                        "start_score",
                        "end_score",
                        "score_leader",
                        "market_favorite",
                        "avg_discrepancy",
                        "max_discrepancy",
                        "duration_min",
                        "initial_discrepancy",
                        "undervalued_side",
                        "price_start",
                        "avg_improvement",
                        "end_improvement",
                        "max_improvement",
                        "forward_max_price",
                        "forward_max_time_seconds",
                        "forward_return",
                        "forward_return_pct",
                        "flip_display",
                        "time_to_flip_display",
                        "correction_ratio_max",
                        "resolution_type",
                    ]
                ].values,
                hovertemplate=(
                    "%{y}<br>"
                    "Type: Lead discrepancy<br>"
                    "Start: %{customdata[0]}<br>"
                    "End: %{customdata[1]}<br>"
                    "Duration: %{customdata[9]:.2f} min<br>"
                    "Trades: %{customdata[2]}<br>"
                    "Score: %{customdata[3]} → %{customdata[4]}<br>"
                    "Score Leader: %{customdata[5]}<br>"
                    "Market Favorite: %{customdata[6]}<br>"
                    "Initial Discrepancy: %{customdata[10]:.4f}<br>"
                    "Avg Discrepancy: %{customdata[7]:.4f}<br>"
                    "Max Discrepancy: %{customdata[8]:.4f}<br>"
                    "Undervalued Side: %{customdata[11]}<br>"
                    "Start Price: %{customdata[12]:.4f}<br>"
                    "Avg Improvement: %{customdata[13]:.4f}<br>"
                    "End Improvement: %{customdata[14]:.4f}<br>"
                    "Max Improvement: %{customdata[15]:.4f}<br>"
                    "Forward Max Price: %{customdata[16]:.4f}<br>"
                    "Time to Forward Max: %{customdata[17]:.1f}s<br>"
                    "Forward Return: %{customdata[18]:+.4f}<br>"
                    "Forward Return %: %{customdata[19]:+.2%}<br>"
                    "Flip: %{customdata[20]}<br>"
                    "Time to Flip: %{customdata[21]}<br>"
                    "Correction Ratio (Max): %{customdata[22]:.4f}<br>"
                    "Resolution: %{customdata[23]}"
                    "<extra></extra>"
                ),
                name="Lead Discrepancy",
            )
        )
    if not tie_df.empty:
        fig.add_trace(
            go.Bar(
                x=tie_df["duration_min"],
                y=tie_df["label"],
                orientation="h",
                base=tie_df["start_time"],
                marker=dict(
                    color=tie_df["avg_discrepancy"],
                    colorscale="Blues",
                    line=dict(color="#222", width=1),
                ),
                customdata=tie_df[
                    [
                        "start_time",
                        "end_time",
                        "trade_count",
                        "start_score",
                        "end_score",
                        "avg_discrepancy",
                        "max_discrepancy",
                        "duration_min",
                        "initial_discrepancy",
                        "price_start",
                        "avg_reversion",
                        "end_reversion",
                        "max_reversion",
                        "forward_max_price",
                        "forward_max_time_seconds",
                        "forward_return",
                        "forward_return_pct",
                        "dead_zone_display",
                        "time_to_dead_zone_display",
                        "reversion_ratio_max",
                        "resolution_type",
                    ]
                ].values,
                hovertemplate=(
                    "%{y}<br>"
                    "Type: Tie discrepancy<br>"
                    "Start: %{customdata[0]}<br>"
                    "End: %{customdata[1]}<br>"
                    "Duration: %{customdata[7]:.2f} min<br>"
                    "Trades: %{customdata[2]}<br>"
                    "Score: %{customdata[3]} → %{customdata[4]}<br>"
                    "Initial Distance From Fair: %{customdata[8]:.4f}<br>"
                    "Avg Discrepancy: %{customdata[5]:.4f}<br>"
                    "Max Discrepancy: %{customdata[6]:.4f}<br>"
                    "Start Price: %{customdata[9]:.4f}<br>"
                    "Avg Reversion: %{customdata[10]:.4f}<br>"
                    "End Reversion: %{customdata[11]:.4f}<br>"
                    "Max Reversion: %{customdata[12]:.4f}<br>"
                    "Forward Max Price: %{customdata[13]:.4f}<br>"
                    "Time to Forward Max: %{customdata[14]:.1f}s<br>"
                    "Forward Return: %{customdata[15]:+.4f}<br>"
                    "Forward Return %: %{customdata[16]:+.2%}<br>"
                    "Returned to Dead Zone: %{customdata[17]}<br>"
                    "Time to Dead Zone: %{customdata[18]}<br>"
                    "Reversion Ratio (Max): %{customdata[19]:.4f}<br>"
                    "Resolution: %{customdata[20]}"
                    "<extra></extra>"
                ),
                name="Tie Discrepancy",
            )
        )
    fig.update_layout(
        template="plotly_dark",
        title=title,
        height=360,
        margin=dict(l=60, r=30, t=50, b=40),
        hovermode="closest",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(title_text="Game Time")
    fig.update_yaxes(title_text="Interval")
    return fig


def build_regime_transitions_chart(
    regime_df: pd.DataFrame | None,
    title: str = "Regime Band Transitions",
) -> go.Figure:
    """Build grouped bars summarizing favorite-side band transitions."""
    if regime_df is None or regime_df.empty:
        return _empty_score_figure(f"{title}: no regime transitions", height=500)

    grouped = _group_transition_rows(regime_df, "period")
    time_grouped = _group_transition_rows(regime_df, "time_bin")
    if grouped.empty and time_grouped.empty:
        return _empty_score_figure(f"{title}: no regime transitions", height=500)

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=False,
        vertical_spacing=0.16,
        subplot_titles=("By Quarter", "By Time Bucket"),
    )
    colors = {"upgrade": "#4CAF50", "downgrade": "#EF5350"}

    for direction in ("upgrade", "downgrade"):
        subset = grouped[grouped["transition_direction"] == direction].sort_values("period")
        if not subset.empty:
            fig.add_trace(
                go.Bar(
                    x=[_period_label(period) for period in subset["period"]],
                    y=subset["mean_forward_return"],
                    name=direction.title(),
                    marker=dict(
                        color=colors[direction],
                        opacity=[0.55 if low else 0.92 for low in subset["low_confidence"]],
                    ),
                    customdata=subset[["event_count", "transition_labels", "median_forward_return"]].values,
                    hovertemplate=(
                        "%{x}<br>"
                        f"Direction: {direction.title()}<br>"
                        "Mean Forward Return: %{y:+.4f}<br>"
                        "Events: %{customdata[0]}<br>"
                        "Transitions: %{customdata[1]}<br>"
                        "Median Forward Return: %{customdata[2]:+.4f}"
                        "<extra></extra>"
                    ),
                    legendgroup=direction,
                    showlegend=True,
                ),
                row=1,
                col=1,
            )

        subset = time_grouped[time_grouped["transition_direction"] == direction].sort_values("time_bin")
        if not subset.empty:
            fig.add_trace(
                go.Bar(
                    x=[_time_bucket_label(bucket) for bucket in subset["time_bin"]],
                    y=subset["mean_forward_return"],
                    name=direction.title(),
                    marker=dict(
                        color=colors[direction],
                        opacity=[0.55 if low else 0.92 for low in subset["low_confidence"]],
                    ),
                    customdata=subset[["event_count", "transition_labels", "median_forward_return"]].values,
                    hovertemplate=(
                        "%{x}<br>"
                        f"Direction: {direction.title()}<br>"
                        "Mean Forward Return: %{y:+.4f}<br>"
                        "Events: %{customdata[0]}<br>"
                        "Transitions: %{customdata[1]}<br>"
                        "Median Forward Return: %{customdata[2]:+.4f}"
                        "<extra></extra>"
                    ),
                    legendgroup=direction,
                    showlegend=False,
                ),
                row=2,
                col=1,
            )

    fig.update_layout(
        template="plotly_dark",
        title=title,
        height=500,
        margin=dict(l=60, r=30, t=60, b=40),
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Mean Forward Return", row=1, col=1)
    fig.update_yaxes(title_text="Mean Forward Return", row=2, col=1)
    fig.update_xaxes(title_text="Quarter", row=1, col=1)
    fig.update_xaxes(title_text="Minutes Since Tipoff", row=2, col=1)
    return fig


def build_dip_recovery_chart(
    dip_df: pd.DataFrame | None,
    title: str = "Price Dip Recovery",
) -> go.Figure:
    """Build grouped bars summarizing absolute-threshold dip recoveries."""
    if dip_df is None or dip_df.empty:
        return _empty_score_figure(f"{title}: no dip events for this game", height=500)

    grouped = _group_dip_rows(dip_df, "period")
    time_grouped = _group_dip_rows(dip_df, "time_bin")
    if grouped.empty and time_grouped.empty:
        return _empty_score_figure(f"{title}: no dip events for this game", height=500)

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=False,
        vertical_spacing=0.16,
        subplot_titles=("By Quarter", "By Time Bucket"),
    )
    threshold_colors = {
        0.05: "#90CAF9",
        0.04: "#42A5F5",
        0.03: "#1E88E5",
        0.02: "#1565C0",
    }

    for threshold in sorted(dip_df["threshold"].dropna().unique(), reverse=True):
        subset = grouped[grouped["threshold"] == threshold].sort_values("period")
        if not subset.empty:
            fig.add_trace(
                go.Bar(
                    x=[_period_label(period) for period in subset["period"]],
                    y=subset["mean_recovery_magnitude"],
                    name=f"{threshold:.0%}",
                    marker=dict(
                        color=threshold_colors.get(float(threshold), "#90CAF9"),
                        opacity=[0.55 if low else 0.92 for low in subset["low_confidence"]],
                    ),
                    customdata=subset[["event_count", "resolutions", "median_recovery_magnitude"]].values,
                    hovertemplate=(
                        "%{x}<br>"
                        f"Threshold: {threshold:.0%}<br>"
                        "Mean Recovery: %{y:.4f}<br>"
                        "Events: %{customdata[0]}<br>"
                        "Resolutions: %{customdata[1]}<br>"
                        "Median Recovery: %{customdata[2]:.4f}"
                        "<extra></extra>"
                    ),
                    legendgroup=f"{threshold:.0%}",
                    showlegend=True,
                ),
                row=1,
                col=1,
            )

        subset = time_grouped[time_grouped["threshold"] == threshold].sort_values("time_bin")
        if not subset.empty:
            fig.add_trace(
                go.Bar(
                    x=[_time_bucket_label(bucket) for bucket in subset["time_bin"]],
                    y=subset["mean_recovery_magnitude"],
                    name=f"{threshold:.0%}",
                    marker=dict(
                        color=threshold_colors.get(float(threshold), "#90CAF9"),
                        opacity=[0.55 if low else 0.92 for low in subset["low_confidence"]],
                    ),
                    customdata=subset[["event_count", "resolutions", "median_recovery_magnitude"]].values,
                    hovertemplate=(
                        "%{x}<br>"
                        f"Threshold: {threshold:.0%}<br>"
                        "Mean Recovery: %{y:.4f}<br>"
                        "Events: %{customdata[0]}<br>"
                        "Resolutions: %{customdata[1]}<br>"
                        "Median Recovery: %{customdata[2]:.4f}"
                        "<extra></extra>"
                    ),
                    legendgroup=f"{threshold:.0%}",
                    showlegend=False,
                ),
                row=2,
                col=1,
            )

    fig.update_layout(
        template="plotly_dark",
        title=title,
        height=500,
        margin=dict(l=60, r=30, t=60, b=40),
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Mean Recovery Magnitude", row=1, col=1)
    fig.update_yaxes(title_text="Mean Recovery Magnitude", row=2, col=1)
    fig.update_xaxes(title_text="Quarter", row=1, col=1)
    fig.update_xaxes(title_text="Minutes Since Tipoff", row=2, col=1)
    return fig


def _empty_score_figure(message: str, height: int = 340) -> go.Figure:
    """Return a placeholder figure when score data is unavailable."""
    fig = go.Figure()
    fig.update_layout(
        template="plotly_dark",
        height=height,
        margin=dict(l=60, r=30, t=40, b=40),
        annotations=[
            dict(
                text=message,
                showarrow=False,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                font=dict(size=16, color="#888"),
            )
        ],
    )
    return fig


def _filter_by_min_cum_vol(trades_df: pd.DataFrame, min_vol: float) -> pd.DataFrame:
    """Drop trades before cumulative volume first reaches min_vol."""
    if trades_df.empty or min_vol <= 0:
        return trades_df.sort_values("datetime")
    sorted_df = trades_df.sort_values("datetime")
    cum = sorted_df["size"].cumsum()
    mask = cum >= min_vol
    if not mask.any():
        return sorted_df  # never reaches threshold — keep all
    return sorted_df.loc[mask]


def _group_sensitivity(plotted: pd.DataFrame, bucket_field: str) -> pd.DataFrame:
    """Aggregate sensitivity rows by bucket and lead context."""
    return (
        plotted.groupby([bucket_field, "lead_bin"], dropna=False)
        .agg(
            mean_abs_delta=("abs_delta_price", "mean"),
            event_count=("delta_price", "size"),
            median_delta=("delta_price", "median"),
            low_confidence=("low_confidence", "any"),
        )
        .reset_index()
    )


def _group_transition_rows(plotted: pd.DataFrame, bucket_field: str) -> pd.DataFrame:
    """Aggregate regime transitions for grouped bar rendering."""
    return (
        plotted.groupby([bucket_field, "transition_direction"], dropna=False)
        .agg(
            mean_forward_return=("forward_return_max", "mean"),
            median_forward_return=("forward_return_max", "median"),
            event_count=("forward_return_max", "size"),
            low_confidence=("low_confidence", "any"),
            transition_labels=("transition_label", lambda values: ", ".join(sorted(set(values)))),
        )
        .reset_index()
    )


def _group_dip_rows(plotted: pd.DataFrame, bucket_field: str) -> pd.DataFrame:
    """Aggregate dip recovery intervals for grouped bar rendering."""
    return (
        plotted.groupby([bucket_field, "threshold"], dropna=False)
        .agg(
            mean_recovery_magnitude=("recovery_magnitude", "mean"),
            median_recovery_magnitude=("recovery_magnitude", "median"),
            event_count=("recovery_magnitude", "size"),
            low_confidence=("low_confidence", "any"),
            resolutions=("resolution", lambda values: ", ".join(sorted(set(values)))),
        )
        .reset_index()
    )


def _period_label(period: int) -> str:
    """Format NBA period numbers for display."""
    period = int(period)
    if period <= 4:
        return f"Q{period}"
    return f"OT{period - 4}"


def _time_bucket_label(bucket: int) -> str:
    """Format six-minute game buckets."""
    bucket = int(bucket)
    start_min = bucket * 6
    end_min = start_min + 6
    return f"{start_min}-{end_min} min"


def _add_period_boundaries(fig: go.Figure, events: list[dict] | None, max_period: int) -> None:
    """Add quarter/OT boundaries using shapes and annotations."""
    tipoff = _get_tipoff(events)
    if tipoff is None:
        return
    for period in range(2, int(max_period) + 1):
        boundary_seconds = _period_boundary_seconds(period)
        if boundary_seconds is None:
            continue
        boundary_time = tipoff + timedelta(seconds=boundary_seconds)
        label = _period_label(period)
        fig.add_shape(
            type="line",
            x0=boundary_time,
            x1=boundary_time,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",
            line=dict(color="#666", width=1, dash="dash"),
        )
        fig.add_annotation(
            x=boundary_time,
            y=1,
            xref="x",
            yref="paper",
            text=label,
            showarrow=False,
            font=dict(size=10, color="#aaa"),
            yshift=10,
        )


def _period_boundary_seconds(period: int) -> int | None:
    """Return elapsed seconds at the start of a period."""
    if period <= 1:
        return None
    if period <= 4:
        return (period - 1) * 12 * 60
    return (4 * 12 * 60) + ((period - 5) * 5 * 60)


def _build_subplot_figure(
    trades_df, away_token, home_token, away_team, home_team,
    title, vmarkers, events, tricode_map, spike_cfg=(2.0, 20),
    whale_addresses=None,
    top_taker_whales=None,
    whale_marker_min_trade_pct=0.25,
    discrete_price_points=False,
) -> go.Figure:
    """Build a subplot figure for a slice of trades."""
    if trades_df.empty:
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark", height=300,
            annotations=[dict(text=f"{title}: no trades", showarrow=False,
                              xref="paper", yref="paper", x=0.5, y=0.5,
                              font=dict(size=18, color="#888"))],
        )
        return fig

    has_aggressor_cumulative = bool(top_taker_whales)
    rows = 4 if has_aggressor_cumulative else 3
    row_heights = [0.45, 0.20, 0.17, 0.18] if has_aggressor_cumulative else [0.55, 0.25, 0.20]
    subplot_titles = (
        ("Price", "Volume", "Cumulative Volume", "Top Aggressor Cumulative")
        if has_aggressor_cumulative
        else ("Price", "Volume", "Cumulative Volume")
    )

    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    # Row 1: Price traces
    away_trades = trades_df[trades_df["asset"] == away_token].sort_values("datetime")
    home_trades = trades_df[trades_df["asset"] == home_token].sort_values("datetime")

    away_label = f"{away_team} (Away)"
    home_label = f"{home_team} (Home)"
    price_mode = "markers" if discrete_price_points else "lines"
    price_marker = dict(size=6) if discrete_price_points else None
    price_line = None if discrete_price_points else dict(width=1.5)
    away_score_leads = _score_lead_series_for_times(away_trades["datetime"], away_team, home_team, events)
    home_score_leads = _score_lead_series_for_times(home_trades["datetime"], away_team, home_team, events)

    fig.add_trace(
        go.Scattergl(
            x=away_trades["datetime"], y=away_trades["price"],
            mode=price_mode, name=away_label,
            line=price_line,
            marker=price_marker,
            customdata=away_score_leads,
            connectgaps=False,
            hovertemplate=(
                "Score Lead: %{customdata}<br>"
                f"Team: {away_label}<br>"
                "Price: %{y:.3f}"
                "<extra></extra>"
            ),
            legend="legend",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scattergl(
            x=home_trades["datetime"], y=home_trades["price"],
            mode=price_mode, name=home_label,
            line=price_line,
            marker=price_marker,
            customdata=home_score_leads,
            connectgaps=False,
            hovertemplate=(
                f"Team: {home_label}<br>"
                "Price: %{y:.3f}"
                "<extra></extra>"
            ),
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

    # Directional whale taker overlay
    if whale_addresses:
        _add_whale_taker_overlays(
            fig, trades_df, whale_addresses,
            away_token, home_token, away_team, home_team,
        )
    if top_taker_whales:
        _add_top_taker_markers(
            fig, trades_df, top_taker_whales,
            away_token, home_token, away_team, home_team,
            whale_marker_min_trade_pct,
        )

    # Row 3: Cumulative volume (4 lines: away buy/sell, home buy/sell)
    _add_cumulative_lines(fig, trades_df, away_token, home_token, away_team, home_team)

    if has_aggressor_cumulative:
        _add_aggressor_cumulative_lines(
            fig, trades_df, top_taker_whales,
            away_token, home_token, away_team, home_team,
        )

    fig.update_layout(
        height=900 if has_aggressor_cumulative else 700,
        template="plotly_dark",
        title=dict(text=title, x=0.02, xanchor="left"),
        showlegend=True,
        # Price legend — above row 1
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1, font=dict(size=11)),
        # Volume legend — above row 2
        legend2=dict(orientation="h", yanchor="bottom", y=0.56 if has_aggressor_cumulative else 0.44,
                     xanchor="right", x=1, font=dict(size=10)),
        # Cumulative legend — above row 3
        legend3=dict(orientation="h", yanchor="bottom", y=0.31 if has_aggressor_cumulative else 0.19,
                     xanchor="right", x=1, font=dict(size=10)),
        legend4=dict(orientation="h", yanchor="bottom", y=0.06,
                     xanchor="right", x=1, font=dict(size=9)),
        margin=dict(l=60, r=30, t=40, b=40),
        hovermode="x unified",
        barmode="stack",
    )
    if has_aggressor_cumulative:
        fig.update_layout(xaxis4=dict(rangeslider=dict(visible=True, thickness=0.05)))
    else:
        fig.update_layout(xaxis3=dict(rangeslider=dict(visible=True, thickness=0.05)))

    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume ($)", row=2, col=1)
    fig.update_yaxes(title_text="Cumulative ($)", row=3, col=1)
    if has_aggressor_cumulative:
        fig.update_yaxes(title_text="Aggressor Cum ($)", row=4, col=1)

    if "global_cum_size" in trades_df.columns:
        _set_pregame_cumulative_axis_range(
            fig, trades_df, away_token, home_token,
        )

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


def _format_score_lead_label(away_team: str, home_team: str, events: list[dict] | None) -> str:
    """Return a compact latest score-lead label for the in-game price title."""
    if not events:
        return ""
    for ev in reversed(events):
        away_score = ev.get("away_score")
        home_score = ev.get("home_score")
        if away_score is None or home_score is None:
            continue
        if away_score > home_score:
            return f"Score Lead: {away_team} +{away_score - home_score}"
        if home_score > away_score:
            return f"Score Lead: {home_team} +{home_score - away_score}"
        return f"Score Lead: Tied {away_score}-{home_score}"
    return ""


def _score_lead_series_for_times(
    times: pd.Series,
    away_team: str,
    home_team: str,
    events: list[dict] | None,
) -> list[str]:
    """Return score-lead labels aligned to trade timestamps using latest known score."""
    if times.empty or not events:
        return ["N/A"] * len(times)

    score_events = [
        ev for ev in events
        if ev.get("time_actual_dt") is not None
        and ev.get("away_score") is not None
        and ev.get("home_score") is not None
    ]
    if not score_events:
        return ["N/A"] * len(times)

    score_df = pd.DataFrame(
        {
            "datetime": [ev["time_actual_dt"] for ev in score_events],
            "away_score": [ev.get("away_score", 0) or 0 for ev in score_events],
            "home_score": [ev.get("home_score", 0) or 0 for ev in score_events],
        }
    ).sort_values("datetime")
    # Normalize both sides of the asof-merge to the same timezone-aware dtype.
    score_df["datetime"] = (
        pd.to_datetime(score_df["datetime"], utc=True)
        .astype("datetime64[ns, UTC]")
    )
    score_df["score_lead"] = score_df.apply(
        lambda row: _score_lead_from_scores(
            away_team,
            home_team,
            int(row["away_score"]),
            int(row["home_score"]),
        ),
        axis=1,
    )

    trade_times = pd.DataFrame(
        {
            "datetime": pd.to_datetime(times, utc=True).astype("datetime64[ns, UTC]")
        }
    )
    merged = pd.merge_asof(
        trade_times.sort_values("datetime"),
        score_df[["datetime", "score_lead"]],
        on="datetime",
        direction="backward",
    )
    return merged["score_lead"].fillna("N/A").tolist()


def _score_lead_from_scores(away_team: str, home_team: str, away_score: int, home_score: int) -> str:
    """Format a compact score-lead label from away/home scores."""
    if away_score > home_score:
        return f"{away_team} +{away_score - home_score}"
    if home_score > away_score:
        return f"{home_team} +{home_score - away_score}"
    return f"Tied {away_score}-{home_score}"


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


def _add_whale_taker_overlays(
    fig,
    trades_df: pd.DataFrame,
    whale_addresses: set[str],
    away_token: str,
    home_token: str,
    away_team: str,
    home_team: str,
):
    """Add taker-only directional whale volume overlays to Row 2."""
    sorted_df = trades_df.sort_values("datetime")
    if sorted_df.empty:
        return

    span = (sorted_df["datetime"].max() - sorted_df["datetime"].min()).total_seconds()
    freq = "1min" if span < 6 * 3600 else "5min"

    # Directional attribution is only reliable for taker whale trades.
    whale_taker = sorted_df[sorted_df["taker"].isin(whale_addresses)]
    if whale_taker.empty:
        return

    # Bucket total volume for hover pct
    total_bucketed = sorted_df.set_index("datetime")["size"].resample(freq).sum().fillna(0)

    overlays = [
        (away_token, away_team, "BUY", "#42A5F5", "rgba(66, 165, 245, 0.24)"),
        (away_token, away_team, "SELL", "#1565C0", "rgba(21, 101, 192, 0.24)"),
        (home_token, home_team, "BUY", "#FFB74D", "rgba(255, 183, 77, 0.24)"),
        (home_token, home_team, "SELL", "#F57C00", "rgba(245, 124, 0, 0.24)"),
    ]

    for token, team, side, line_color, fill_color in overlays:
        label = f"{team} Whale {side.title()}"
        whale_side = whale_taker[
            (whale_taker["asset"] == token) & (whale_taker["side"] == side)
        ]
        if whale_side.empty:
            continue

        bucketed = whale_side.set_index("datetime")["size"].resample(freq).sum().fillna(0)
        bucketed = bucketed.reindex(total_bucketed.index, fill_value=0)

        pct_text = [
            f"${wv:,.0f} ({wv / tv * 100:.0f}%)" if tv > 0 else "$0"
            for wv, tv in zip(bucketed.values, total_bucketed.values)
        ]

        fig.add_trace(
            go.Scatter(
                x=bucketed.index, y=bucketed.values,
                mode="lines", fill="tozeroy",
                line=dict(color=line_color, width=2),
                fillcolor=fill_color,
                name=label,
                text=pct_text,
                hovertemplate="%{x}<br>%{text}<extra>" + label + "</extra>",
                legend="legend2",
            ),
            row=2, col=1,
        )


def _add_top_taker_markers(
    fig,
    trades_df: pd.DataFrame,
    top_taker_whales: list[dict],
    away_token: str,
    home_token: str,
    away_team: str,
    home_team: str,
    whale_marker_min_trade_pct: float = 0.25,
):
    """Add price-row markers for the ranked top taker whale trades."""
    if trades_df.empty or not top_taker_whales:
        return

    min_trade_size = trades_df["size"].sum() * (whale_marker_min_trade_pct / 100.0)
    rank_map = {w["address"]: idx for idx, w in enumerate(top_taker_whales, start=1)}
    ranked_trades = trades_df[
        trades_df["taker"].isin(rank_map) & (trades_df["size"] >= min_trade_size)
    ].copy()
    if ranked_trades.empty:
        return

    team_map = {away_token: away_team, home_token: home_team}
    ranked_trades["rank"] = ranked_trades["taker"].map(rank_map)
    ranked_trades["team_name"] = ranked_trades["asset"].map(team_map).fillna("")

    marker_specs = [
        (away_token, "BUY", "#42A5F5", "triangle-up"),
        (away_token, "SELL", "#1565C0", "triangle-down"),
        (home_token, "BUY", "#FFB74D", "triangle-up"),
        (home_token, "SELL", "#F57C00", "triangle-down"),
    ]

    for token, side, color, symbol in marker_specs:
        subset = ranked_trades[
            (ranked_trades["asset"] == token) & (ranked_trades["side"] == side)
        ].sort_values("datetime")
        if subset.empty:
            continue

        label = f"{team_map[token]} Top-10 Whale {side.title()}"
        customdata = subset[["rank", "size", "team_name", "side"]].values

        fig.add_trace(
            go.Scattergl(
                x=subset["datetime"],
                y=subset["price"],
                mode="markers+text",
                text=[f"#{rank}" for rank in subset["rank"]],
                textposition="top center",
                textfont=dict(size=9, color=color),
                marker=dict(
                    size=10,
                    color=color,
                    symbol=symbol,
                    line=dict(width=1, color="#111"),
                ),
                customdata=customdata,
                name=label,
                hovertemplate=(
                    "%{x}<br>"
                    "Rank: #%{customdata[0]}<br>"
                    "Trade: %{customdata[2]} %{customdata[3]}<br>"
                    "Amount: $%{customdata[1]:,.0f}<br>"
                    "Price: %{y:.3f}"
                    "<extra>" + label + "</extra>"
                ),
                legend="legend",
            ),
            row=1, col=1,
        )


def _add_cumulative_lines(fig, trades_df: pd.DataFrame,
                          away_token: str, home_token: str,
                          away_team: str, home_team: str):
    """Add directional cumulative lines plus total cumulative volume to Row 3."""
    sorted_df = trades_df.sort_values("datetime")

    if "global_cum_size" in sorted_df.columns:
        fig.add_trace(
            go.Scattergl(
                x=sorted_df["datetime"],
                y=sorted_df["global_cum_size"],
                mode="lines",
                name="Total Cum Volume",
                line=dict(color="#E0E0E0", width=2, dash="dash"),
                hovertemplate="%{x}<br>$%{y:,.0f}<extra>Total Cum Volume</extra>",
                legend="legend3",
            ),
            row=3, col=1,
        )

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
        if "asset_side_cum_size" in subset.columns:
            cum = subset["asset_side_cum_size"]
        else:
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


def _set_pregame_cumulative_axis_range(
    fig: go.Figure,
    trades_df: pd.DataFrame,
    away_token: str,
    home_token: str,
):
    """Keep pregame cumulative axes anchored to visible cumulative values."""
    visible_mins: list[float] = []
    visible_maxs: list[float] = []

    global_cum = trades_df.get("global_cum_size")
    if global_cum is not None and not global_cum.empty:
        visible_mins.append(float(global_cum.min()))
        visible_maxs.append(float(global_cum.max()))

    for token, side in [
        (away_token, "BUY"),
        (away_token, "SELL"),
        (home_token, "BUY"),
        (home_token, "SELL"),
    ]:
        subset = trades_df[(trades_df["asset"] == token) & (trades_df["side"] == side)]
        if subset.empty:
            continue
        if "asset_side_cum_size" in subset.columns:
            cum = subset["asset_side_cum_size"]
        else:
            cum = subset["size"].cumsum()
        visible_mins.append(float(cum.min()))
        visible_maxs.append(float(cum.max()))

    if not visible_mins or not visible_maxs:
        return

    min_val = min(visible_mins)
    max_val = max(visible_maxs)
    if min_val == max_val:
        lower = min_val * 0.95 if min_val > 0 else 0.0
        upper = max_val * 1.05 if max_val > 0 else 1.0
    else:
        pad = (max_val - min_val) * 0.05
        lower = max(min_val - pad, min_val * 0.95 if min_val > 0 else 0.0)
        upper = max_val + pad

    fig.update_yaxes(range=[lower, upper], row=3, col=1)


def _add_aggressor_cumulative_lines(
    fig,
    trades_df: pd.DataFrame,
    top_taker_whales: list[dict],
    away_token: str,
    home_token: str,
    away_team: str,
    home_team: str,
):
    """Add cumulative taker-flow lines for the ranked top aggressor wallets."""
    if trades_df.empty or not top_taker_whales:
        return

    sorted_df = trades_df.sort_values("datetime")
    rank_palette = [
        "#00BCD4", "#8BC34A", "#E91E63", "#9C27B0", "#FFC107",
        "#03A9F4", "#CDDC39", "#FF5722", "#673AB7", "#009688",
    ]
    team_meta = {
        away_token: {"team": away_team, "dash_buy": "solid", "dash_sell": "dot"},
        home_token: {"team": home_team, "dash_buy": "dash", "dash_sell": "dashdot"},
    }

    for idx, whale in enumerate(top_taker_whales, start=1):
        wallet = whale["address"]
        wallet_trades = sorted_df[sorted_df["taker"] == wallet]
        if wallet_trades.empty:
            continue

        color = rank_palette[(idx - 1) % len(rank_palette)]
        for token, side in [
            (away_token, "BUY"),
            (away_token, "SELL"),
            (home_token, "BUY"),
            (home_token, "SELL"),
        ]:
            subset = wallet_trades[
                (wallet_trades["asset"] == token) & (wallet_trades["side"] == side)
            ]
            if subset.empty:
                continue

            team_name = team_meta[token]["team"]
            dash = team_meta[token]["dash_buy"] if side == "BUY" else team_meta[token]["dash_sell"]
            cum = subset["size"].cumsum()
            label = f"#{idx} {team_name} {side.title()}"

            fig.add_trace(
                go.Scattergl(
                    x=subset["datetime"],
                    y=cum,
                    mode="lines",
                    name=label,
                    line=dict(color=color, width=1.8, dash=dash),
                    hovertemplate="%{x}<br>$%{y:,.0f}<extra>" + label + "</extra>",
                    legend="legend4",
                ),
                row=4, col=1,
            )
