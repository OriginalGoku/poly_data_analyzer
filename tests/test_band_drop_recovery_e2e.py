"""End-to-end test: sweep scenario -> engine -> aggregator.

The universe filter and per-game context builder are stubbed so the test runs
without a real on-disk data directory (poly-data-downloader fixtures are
prohibitively large for unit tests). The engine, sweep expansion, and
aggregator are exercised end-to-end.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from unittest.mock import patch

from band_drop_recovery import compute_recovery_grid
from backtest.contracts import Context, GameMeta
from backtest.runner import run as run_scenarios
from backtest.scenarios import load_scenarios

import backtest.exits  # noqa: F401
import backtest.filters  # noqa: F401
import backtest.triggers  # noqa: F401


ACTIVE_BANDS = (
    "Lean Favorite",
    "Lower Moderate",
    "Upper Moderate",
    "Lower Strong",
    "Upper Strong",
)
DROPS = (10, 20, 30, 40, 50, 60, 70, 80, 90, 95)


def _make_meta(date: str, match_id: str, tipoff_fav: float) -> GameMeta:
    return GameMeta(
        date=date,
        match_id=match_id,
        sport="nba",
        open_fav_price=tipoff_fav,
        tipoff_fav_price=tipoff_fav,
        open_fav_token_id=f"tok-{match_id}",
        can_settle=True,
        price_quality="live",
        open_favorite_team="FAV",
    )


def _make_context(scenario, gm: GameMeta, drops_to_then_recovers: bool, deepest_drop_pct: float):
    """Build a Context with a tipoff-anchored price path that drops then maybe recovers."""
    tipoff = pd.Timestamp("2026-01-01 19:00:00")
    game_end = tipoff + pd.Timedelta(hours=3)
    fav = gm.tipoff_fav_price
    min_price = fav * (1.0 - deepest_drop_pct / 100.0)
    # Synthetic trade tape: tipoff -> linear drop to min -> linear back to fav (or not)
    n_down = 30
    n_up = 30
    rows = []
    for i in range(n_down):
        t = tipoff + pd.Timedelta(minutes=i + 1)
        p = fav + (min_price - fav) * (i + 1) / n_down
        rows.append({"datetime": t, "team": "FAV", "price": float(p), "token_id": gm.open_fav_token_id})
    if drops_to_then_recovers:
        for i in range(n_up):
            t = tipoff + pd.Timedelta(minutes=n_down + i + 1)
            p = min_price + (fav - min_price) * (i + 1) / n_up
            rows.append({"datetime": t, "team": "FAV", "price": float(p), "token_id": gm.open_fav_token_id})
    trades_df = pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)
    arr = np.array(trades_df["datetime"].values, dtype="datetime64[ns]")
    return Context(
        trades_df=trades_df,
        trades_time_array=arr,
        favorite_team="FAV",
        underdog_team="DOG",
        open_prices={"FAV": fav, "DOG": 1 - fav},
        tipoff_prices={"FAV": fav, "DOG": 1 - fav},
        tipoff_time=tipoff,
        game_end=game_end,
        game_meta=gm,
        scenario=scenario,
        settings={"manifest": {}, "events": None},
    )


def test_sweep_end_to_end_with_synthetic_games():
    # Two NBA games: Upper Strong recovers from 30% drop; Lower Moderate doesn't recover from 50%.
    g1 = _make_meta("2026-01-01", "g1", tipoff_fav=0.90)   # Upper Strong
    g2 = _make_meta("2026-01-02", "g2", tipoff_fav=0.60)   # Lower Moderate

    games_by_match = {
        ("g1",): (g1, True, 30.0),
        ("g2",): (g2, False, 50.0),
    }

    def fake_universe(start_date, end_date, params):
        return [g1, g2]

    def fake_builder(gm, scenario, data_dir, settings):
        meta, recovers, deepest = games_by_match[(gm.match_id,)]
        return _make_context(scenario, meta, recovers, deepest)

    scenarios = [
        s for n, s in load_scenarios("backtest/scenarios").items()
        if n.startswith("band_drop_recovery_sweep")
    ]
    assert len(scenarios) == 10

    with patch.dict("backtest.registry.UNIVERSE_FILTERS", {"first_k_above": fake_universe}):
        positions_df, _agg = run_scenarios(
            scenarios,
            datetime(2026, 1, 1),
            datetime(2026, 1, 31),
            "data",
            {},
            context_builder=fake_builder,
        )

    assert not positions_df.empty
    # g1 (Upper Strong, recovers) triggers at 10/20/30 and recovers each time.
    # g2 (Lower Moderate, no recover) triggers at 10..50 but force-closes.
    base_records = pd.DataFrame(
        [
            {"date": "2026-01-01", "match_id": "g1", "sport": "nba",
             "open_interpretable_band": "Upper Strong", "tipoff_favorite_price": 0.90,
             "open_favorite_price": 0.90, "price_quality": "live"},
            {"date": "2026-01-02", "match_id": "g2", "sport": "nba",
             "open_interpretable_band": "Lower Moderate", "tipoff_favorite_price": 0.60,
             "open_favorite_price": 0.60, "price_quality": "live"},
        ]
    )
    out = compute_recovery_grid(positions_df, base_records, ACTIVE_BANDS, DROPS)
    grid = out["grid"]

    # TS2: Upper Strong cells at 10/20/30 all recovered.
    for d in (10, 20, 30):
        cell = grid.at["Upper Strong", float(d)]
        assert cell["n"] == 1 and cell["rate"] == 1.0
    # Upper Strong at 40 onward: 0 trades (didn't drop that deep).
    for d in (40, 50, 60, 70, 80, 90, 95):
        cell = grid.at["Upper Strong", float(d)]
        assert cell["n"] == 0

    # TS5/TS2: Lower Moderate at 10/20/30/40/50 triggered but did not recover.
    for d in (10, 20, 30, 40, 50):
        cell = grid.at["Lower Moderate", float(d)]
        assert cell["n"] == 1
        assert cell["rate"] == 0.0
    # Lower Moderate at 60+: no trigger (only dropped to 50%).
    for d in (60, 70, 80, 90, 95):
        cell = grid.at["Lower Moderate", float(d)]
        assert cell["n"] == 0

    # TS13: cumulative invariant — shallower N >= deeper N for any band.
    for band in ACTIVE_BANDS:
        prev_n = None
        for d in DROPS:
            n = grid.at[band, float(d)]["n"]
            if prev_n is not None:
                assert n <= prev_n, f"cumulative violated at band={band}, drop={d}"
            prev_n = n
