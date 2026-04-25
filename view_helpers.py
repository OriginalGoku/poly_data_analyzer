"""Reusable Dash view helpers."""

from __future__ import annotations

from dash import dcc, html


APP_SHELL_STYLE = {
    "backgroundColor": "#111",
    "minHeight": "100vh",
    "padding": "20px",
    "fontFamily": "system-ui, sans-serif",
    "color": "#eee",
}

CARD_STYLE = {
    "backgroundColor": "#1a1a2e",
    "padding": "15px",
    "borderRadius": "8px",
}


def info_row(label, value):
    return html.Div(
        style={
            "display": "flex",
            "justifyContent": "space-between",
            "padding": "3px 0",
            "borderBottom": "1px solid #333",
            "gap": "16px",
        },
        children=[
            html.Span(label, style={"color": "#888"}),
            html.Span(str(value), style={"fontWeight": "bold", "textAlign": "right"}),
        ],
    )


def format_prob(price):
    if price is None:
        return "N/A"
    return f"{price:.3f} ({price * 100:.1f}%)"


def format_quantile_cutoffs(cutoffs):
    if not cutoffs:
        return "N/A"
    q1, q2 = cutoffs
    return f"Q1 < {q1:.3f}, Q2 < {q2:.3f}, Q3 >= {q2:.3f}"


def build_navbar(active_path: str) -> html.Div:
    links = [
        ("Main Dashboard", "/"),
        ("NBA Open vs Tip-Off", "/nba-open-tipoff-analysis"),
        ("Backtest Results", "/backtest-results"),
        ("Run Backtest", "/run-backtest"),
        ("Scenario Runner", "/scenario-runner"),
        ("Scenario Results", "/scenario-results"),
    ]
    return html.Div(
        style={
            "display": "flex",
            "gap": "10px",
            "marginBottom": "20px",
            "flexWrap": "wrap",
        },
        children=[
            dcc.Link(
                label,
                href=href,
                style={
                    "padding": "8px 12px",
                    "borderRadius": "6px",
                    "textDecoration": "none",
                    "color": "#111" if href == active_path else "#ddd",
                    "backgroundColor": "#9ad1ff" if href == active_path else "#222",
                    "border": "1px solid #333",
                    "fontWeight": "bold" if href == active_path else "normal",
                },
            )
            for label, href in links
        ],
    )
