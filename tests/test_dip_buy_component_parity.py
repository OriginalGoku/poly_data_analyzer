"""Parity test: dip_below_anchor vs legacy find_dip_entry.

Five synthetic Context fixtures exercising distinct paths. For each, the new
trigger's (timestamp, price) must match find_dip_entry exactly.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from backtest.contracts import (
    ComponentSpec,
    Context,
    GameMeta,
    LockSpec,
    Scenario,
)
from backtest.dip_entry_detection import find_dip_entry
from backtest.triggers.dip_below_anchor import dip_below_anchor


FAV = "FAV"
DOG = "DOG"
TIPOFF = datetime(2026, 3, 23, 19, 30, 0)
GAME_END = TIPOFF + timedelta(hours=2, minutes=30)
OPEN_PRICE = 0.92


def _ctx(trades_df: pd.DataFrame) -> Context:
    df = trades_df.sort_values("datetime").reset_index(drop=True)
    arr = df["datetime"].to_numpy(dtype="datetime64[ns]")
    meta = GameMeta(
        date="2026-03-23",
        match_id="m",
        sport="nba",
        open_fav_price=OPEN_PRICE,
        tipoff_fav_price=OPEN_PRICE,
        open_fav_token_id="tok_fav",
        can_settle=True,
        price_quality="ok",
        open_favorite_team=FAV,
    )
    scenario = Scenario(
        name="s",
        universe_filter=ComponentSpec(name="upper_strong"),
        side_target="favorite",
        trigger=ComponentSpec(name="dip_below_anchor"),
        exit=ComponentSpec(name="settlement"),
        lock=LockSpec(mode="sequential"),
        fee_model="taker",
    )
    return Context(
        trades_df=df,
        trades_time_array=arr,
        favorite_team=FAV,
        underdog_team=DOG,
        open_prices={FAV: OPEN_PRICE, DOG: 1 - OPEN_PRICE},
        tipoff_prices={FAV: OPEN_PRICE, DOG: 1 - OPEN_PRICE},
        tipoff_time=pd.Timestamp(TIPOFF),
        game_end=pd.Timestamp(GAME_END),
        game_meta=meta,
        scenario=scenario,
    )


def _df(rows):
    # rows: list of (datetime, price)
    return pd.DataFrame(
        [(t, p, FAV, "tok_fav") for t, p in rows],
        columns=["datetime", "price", "team", "token_id"],
    )


# Five distinct fixtures.
NO_DIP = _df([
    (TIPOFF + timedelta(minutes=1), 0.92),
    (TIPOFF + timedelta(minutes=2), 0.91),
    (TIPOFF + timedelta(minutes=3), 0.93),
])

SINGLE_DIP = _df([
    (TIPOFF + timedelta(minutes=1), 0.92),
    (TIPOFF + timedelta(minutes=2), 0.81),
    (TIPOFF + timedelta(minutes=3), 0.85),
])

MULTIPLE_DIPS = _df([
    (TIPOFF + timedelta(minutes=1), 0.92),
    (TIPOFF + timedelta(minutes=2), 0.80),
    (TIPOFF + timedelta(minutes=3), 0.85),
    (TIPOFF + timedelta(minutes=4), 0.78),
    (TIPOFF + timedelta(minutes=5), 0.75),
])

EDGE_OF_THRESHOLD = _df([
    (TIPOFF + timedelta(minutes=1), 0.83),     # threshold 10 -> dip_level 0.82, miss
    (TIPOFF + timedelta(minutes=2), 0.82),     # exactly equal — must trigger
    (TIPOFF + timedelta(minutes=3), 0.84),
])

POST_TIPOFF_ONLY = _df([
    (TIPOFF - timedelta(minutes=10), 0.50),    # pregame deep dip — must be ignored
    (TIPOFF + timedelta(minutes=2), 0.81),
])


CASES = [
    ("no_dip", NO_DIP, 10),
    ("single_dip", SINGLE_DIP, 10),
    ("multiple_dips", MULTIPLE_DIPS, 10),
    ("edge_of_threshold", EDGE_OF_THRESHOLD, 10),
    ("post_tipoff_only", POST_TIPOFF_ONLY, 10),
]


@pytest.mark.parametrize("name,df,threshold", CASES, ids=[c[0] for c in CASES])
def test_parity_with_find_dip_entry(name, df, threshold):
    legacy = find_dip_entry(
        df,
        open_price=OPEN_PRICE,
        dip_threshold_cents=threshold,
        tipoff_time=TIPOFF,
        game_end=GAME_END,
        settings=None,
    )

    ctx = _ctx(df)
    new = dip_below_anchor(
        ctx, TIPOFF, {"anchor": "open", "threshold_cents": threshold}
    )

    if legacy is None:
        assert new is None, f"{name}: expected no trigger, got {new}"
    else:
        assert new is not None, f"{name}: expected trigger, got None"
        assert new.trigger_time == pd.Timestamp(legacy["entry_time"]), name
        assert new.trigger_price == legacy["entry_price"], name
