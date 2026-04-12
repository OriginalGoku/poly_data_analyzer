"""Tests for analytics card rendering helpers in app.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import _build_analysis_card
from tests.test_app import _flatten_text


def test_build_analysis_card_shows_open_and_tipoff_regimes():
    summary = {
        "sport": "nba",
        "price_quality": "exact",
        "population_games": 321,
        "open": {
            "team": "Lakers",
            "price": 0.61,
            "source": "clob_open",
            "interpretable_band": "Lower Moderate",
            "quantile_band": "Q2",
            "quantile_cutoffs": (0.54, 0.76),
        },
        "tipoff": {
            "team": "Lakers",
            "price": 0.68,
            "source": "last_pregame_trade",
            "interpretable_band": "Upper Moderate",
            "quantile_band": "Q3",
            "quantile_cutoffs": (0.57, 0.66),
        },
    }

    card = _build_analysis_card(summary, "all")
    text = " ".join(_flatten_text(card))

    assert "Game Analytics" in text
    assert "Market Open Regime" in text
    assert "Tip-Off Regime" in text
    assert "Lakers" in text
    assert "Lower Moderate" in text
    assert "Upper Moderate" in text
    assert "Q2" in text
    assert "Q3" in text
    assert "321" in text
