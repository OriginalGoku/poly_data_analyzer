"""Tests for the live win-probability model + mispricing test (Lever 3)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nba_tipoff_winprob import (
    _lead_bucket,
    _price_asof,
    _time_bucket,
    build_win_prob_table,
    evaluate_mispricing,
    extract_game_samples,
)


def test_time_and_lead_buckets():
    assert _time_bucket(0) == "0-12m"
    assert _time_bucket(13) == "12-24m"
    assert _time_bucket(47) == "36-48m"
    assert _time_bucket(60) == "48-200m"  # OT absorbed
    assert _lead_bucket(0) == "[-3,3)"
    assert _lead_bucket(10) == "[8,15)"
    assert _lead_bucket(-20) == "[-100,-15)"


def test_price_asof_last_at_or_before():
    base = pd.Timestamp("2026-04-10T19:00:00Z")
    times = np.array(
        [np.datetime64(pd.Timestamp(base + pd.Timedelta(minutes=m)), "ns") for m in (10, 20, 30)]
    )
    prices = np.array([0.6, 0.7, 0.8])
    assert _price_asof(times, prices, base + pd.Timedelta(minutes=25)) == pytest.approx(0.7)
    assert _price_asof(times, prices, base + pd.Timedelta(minutes=30)) == pytest.approx(0.8)
    assert _price_asof(times, prices, base + pd.Timedelta(minutes=5)) is None
    assert _price_asof(np.array([], dtype="datetime64[ns]"), np.array([]), base) is None


def _game(fav_is_away=True):
    t0 = pd.Timestamp("2026-04-10T19:00:00Z")
    events = [
        {"time_actual_dt": t0, "away_score": 0, "home_score": 0},
        {"time_actual_dt": t0 + pd.Timedelta(minutes=13), "away_score": 30, "home_score": 22},
        {"time_actual_dt": t0 + pd.Timedelta(minutes=40), "away_score": 95, "home_score": 90},
    ]
    trades_df = pd.DataFrame(
        {
            "datetime": [t0 - pd.Timedelta(minutes=1), t0 + pd.Timedelta(minutes=12), t0 + pd.Timedelta(minutes=39)],
            "asset": ["a1", "a1", "a1"],
            "price": [0.70, 0.80, 0.88],
            "size": [100, 100, 100],
        }
    )
    manifest = {"token_ids": ["a1", "h1"], "outcomes": ["Away", "Home"]}
    return events, trades_df, manifest


def test_extract_game_samples_lead_and_price():
    events, trades_df, manifest = _game()
    samples = extract_game_samples(events, trades_df, manifest, "Away", won=True, date="2026-04-10", match_id="g1")
    # Three events at elapsed 0, 13, 40 minutes.
    assert len(samples) == 3
    s13 = next(s for s in samples if s["time_bucket"] == "12-24m")
    assert s13["lead"] == 8  # 30 - 22, favorite is away
    assert s13["lead_bucket"] == "[8,15)"
    assert s13["market_price"] == pytest.approx(0.80)  # asof the 12-min trade
    assert all(s["won"] for s in samples)


def test_build_win_prob_table_and_mispricing_ev():
    # Two synthetic states; in one, model says 0.90 win while market priced 0.70 (underpriced).
    train = pd.DataFrame(
        {
            "time_bucket": ["12-24m"] * 10,
            "lead_bucket": ["[8,15)"] * 10,
            "won": [True] * 9 + [False],  # 90% win
            "market_price": [0.70] * 10,
        }
    )
    table = build_win_prob_table(train)
    assert table.iloc[0]["win_rate"] == pytest.approx(0.9)

    test = pd.DataFrame(
        {
            "time_bucket": ["12-24m"] * 8,
            "lead_bucket": ["[8,15)"] * 8,
            "won": [True] * 6 + [False] * 2,  # realized 75%
            "market_price": [0.70] * 8,
        }
    )
    miss = evaluate_mispricing(test, table)
    # edge = 0.90 - 0.70 = 0.20 -> high-edge bucket; EV = 0.75 - 0.70 = 0.05
    row = miss.iloc[0]
    assert row["edge_bucket"] == "[+0.10,+1.00)"
    assert row["ev_per_unit_stake"] == pytest.approx(0.05)


def test_mispricing_empty_inputs():
    assert evaluate_mispricing(pd.DataFrame(), pd.DataFrame()).empty
    assert build_win_prob_table(pd.DataFrame()).empty
