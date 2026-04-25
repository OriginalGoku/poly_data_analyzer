"""Underdog full-pipeline test for backtest.runner.

Verifies that when scenario.side_target == "underdog":
  - the engine triggers on the underdog team
  - settlement direction matches the underdog team
  - baseline columns are NaN (baselines are favorite-only)
"""
from __future__ import annotations

from datetime import datetime
from typing import Mapping, Optional

import numpy as np
import pandas as pd
import pytest

from backtest import runner
from backtest.contracts import (
    ComponentSpec,
    Context,
    GameMeta,
    LockSpec,
    Scenario,
    Trigger,
)
from backtest.registry import EXITS, TRIGGERS, UNIVERSE_FILTERS


T0 = pd.Timestamp("2025-04-01 18:00:00", tz="UTC")
GAME_END = T0 + pd.Timedelta(hours=2)


@pytest.fixture
def register_components():
    added_t: list[str] = []
    added_e: list[str] = []
    added_u: list[str] = []

    def add_trigger(name, fn):
        TRIGGERS[name] = fn
        added_t.append(name)

    def add_exit(name, fn):
        EXITS[name] = fn
        added_e.append(name)

    def add_universe(name, fn):
        UNIVERSE_FILTERS[name] = fn
        added_u.append(name)

    yield add_trigger, add_exit, add_universe

    for n in added_t:
        TRIGGERS.pop(n, None)
    for n in added_e:
        EXITS.pop(n, None)
    for n in added_u:
        UNIVERSE_FILTERS.pop(n, None)


def _underdog_trigger(ctx: Context, after_time, params) -> Optional[Trigger]:
    """Fires on the first underdog trade strictly after `after_time`."""
    sliced = ctx.slice_after(after_time, team=ctx.underdog_team)
    if sliced.empty:
        return None
    if ctx.game_end is not None:
        sliced = sliced[sliced["datetime"] < ctx.game_end]
        if sliced.empty:
            return None
    row = sliced.iloc[0]
    return Trigger(
        trigger_time=row["datetime"],
        trigger_price=float(row["price"]),
        team=ctx.underdog_team,
        token_id=f"tok-{ctx.underdog_team}",
        side="yes",
    )


def _noop_exit_factory(ctx, trigger, params):
    def scan(ctx_, now):
        return None

    return scan


def _build_underdog_context(
    game_meta: GameMeta,
    scenario: Scenario,
    data_dir: str,
    settings: Mapping[str, object],
) -> Context:
    rows = []
    for i in range(20):
        # AAA (favorite) trends up; BBB (underdog) drifts down — but underdog WINS
        # in events (away_score > home_score; AAA is away_team in manifest below
        # → favorite is away → underdog is home → home wins).
        price_aaa = min(0.95, 0.70 + i * 0.005)
        rows.append(
            {
                "datetime": T0 + pd.Timedelta(seconds=10 * i),
                "team": "AAA",
                "price": price_aaa,
                "asset": "tok-AAA",
                "size": 100.0,
            }
        )
        rows.append(
            {
                "datetime": T0 + pd.Timedelta(seconds=10 * i + 1),
                "team": "BBB",
                "price": 1.0 - price_aaa,
                "asset": "tok-BBB",
                "size": 100.0,
            }
        )
    trades = pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)
    arr = np.array(trades["datetime"].values, dtype="datetime64[ns]")

    # AAA = away (favorite), BBB = home (underdog).
    manifest = {
        "away_team": "AAA",
        "home_team": "BBB",
        "token_ids": ["tok-AAA", "tok-BBB"],
    }
    # Home team wins → underdog wins → BBB pays out.
    events = [
        {
            "period": 4,
            "away_score": 95,
            "home_score": 110,
            "time_actual_dt": T0 + pd.Timedelta(hours=1, minutes=45),
        }
    ]
    ctx_settings = dict(settings)
    ctx_settings["manifest"] = manifest
    ctx_settings["events"] = events
    return Context(
        trades_df=trades,
        trades_time_array=arr,
        favorite_team="AAA",
        underdog_team="BBB",
        open_prices={"AAA": 0.7, "BBB": 0.3},
        tipoff_prices={"AAA": 0.7, "BBB": 0.3},
        tipoff_time=T0,
        game_end=GAME_END,
        game_meta=game_meta,
        scenario=scenario,
        settings=ctx_settings,
    )


def test_underdog_full_pipeline_baselines_nan_settlement_direction_correct(register_components):
    add_trigger, add_exit, add_universe = register_components
    add_trigger("ud_first_trade", _underdog_trigger)
    add_exit("ud_noop_exit", _noop_exit_factory)

    game = GameMeta(
        date="2025-04-01",
        match_id="ud1",
        sport="nba",
        open_fav_price=0.70,
        tipoff_fav_price=0.70,
        open_fav_token_id="tok-AAA",
        can_settle=True,
        price_quality="good",
        open_favorite_team="AAA",
    )
    add_universe("ud_uni", lambda s, e, p: [game])

    scenario = Scenario(
        name="underdog_first_trade",
        universe_filter=ComponentSpec("ud_uni", {}),
        side_target="underdog",
        trigger=ComponentSpec("ud_first_trade", {}),
        exit=ComponentSpec("ud_noop_exit", {}),
        lock=LockSpec(mode="sequential", max_entries=1, cool_down_seconds=0.0),
        fee_model="taker",
    )

    per_position_df, aggregation_df = runner.run(
        scenarios=[scenario],
        start_date=datetime(2025, 4, 1),
        end_date=datetime(2025, 4, 1),
        data_dir="data",
        settings={},
        context_builder=_build_underdog_context,
    )

    assert len(per_position_df) == 1
    row = per_position_df.iloc[0]

    assert row["side"] == "underdog"
    assert row["entry_team"] == "BBB"
    # Sliced to underdog: first BBB trade is at T0 + 1s.
    assert row["entry_price"] == pytest.approx(0.30)

    # Baseline columns are NaN for underdog.
    assert pd.isna(row["baseline_buy_at_open_roi"])
    assert pd.isna(row["baseline_buy_at_tipoff_roi"])
    assert pd.isna(row["baseline_buy_first_ingame_roi"])

    # Settlement: home (BBB) wins → underdog payout = 1.0.
    assert row["settlement_payout"] == 1.0

    # Aggregation has one row.
    assert len(aggregation_df) == 1
    assert aggregation_df.iloc[0]["count"] == 1
