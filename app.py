"""Dash app entry point with dedicated routes."""

from __future__ import annotations

from pathlib import Path

from dash import Dash, Input, Output, dcc, html

from nba_analysis import NBAOpenTipoffAnalysisService
from pages.backtest_results_page import BacktestResultsPage
from pages.backtest_runner_page import BacktestRunnerPage
from pages.main_dashboard_page import MainDashboardPage, _build_analysis_card, _build_whale_card
from pages.nba_open_tipoff_page import NBAOpenTipoffAnalysisPage
from settings import load_chart_settings
from view_helpers import APP_SHELL_STYLE, build_navbar

DATA_DIR = "data"
SETTINGS_PATH = Path(__file__).parent / "chart_settings.json"
SETTINGS = load_chart_settings(SETTINGS_PATH)

app = Dash(__name__, suppress_callback_exceptions=True)

main_page = MainDashboardPage(DATA_DIR, SETTINGS)
nba_analysis_page = NBAOpenTipoffAnalysisPage(
    analysis_service=NBAOpenTipoffAnalysisService(DATA_DIR, SETTINGS),
    settings=SETTINGS,
)
backtest_page = BacktestResultsPage()
backtest_runner_page = BacktestRunnerPage()
PAGES = {
    main_page.route: main_page,
    nba_analysis_page.route: nba_analysis_page,
    backtest_page.route: backtest_page,
    backtest_runner_page.route: backtest_runner_page,
}


app.layout = html.Div(
    style=APP_SHELL_STYLE,
    children=[
        dcc.Location(id="url"),
        html.Div(id="app-shell"),
    ],
)


@app.callback(Output("app-shell", "children"), Input("url", "pathname"))
def render_page(pathname):
    page = PAGES.get(pathname or "/", main_page)
    return [build_navbar(page.route), page.layout()]


main_page.register_callbacks(app)
nba_analysis_page.register_callbacks(app)
backtest_page.register_callbacks(app)
backtest_runner_page.register_callbacks(app)


if __name__ == "__main__":
    app.run(debug=True)
