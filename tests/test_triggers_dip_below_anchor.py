"""Tests for backtest.triggers.dip_below_anchor."""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backtest.contracts import (
    ComponentSpec,
    Context,
    GameMeta,
    LockSpec,
    Scenario,
)
from backtest.registry import TRIGGERS
from backtest.triggers.dip_below_anchor import dip_below_anchor


FAV = "FAV"
DOG = "DOG"


def _make_ctx(trades_df: pd.DataFrame, tipoff: datetime, game_end: datetime,
              open_fav: float = 0.92, tipoff_fav: float = 0.92) -> Context:
    df = trades_df.sort_values("datetime").reset_index(drop=True)
    time_arr = df["datetime"].to_numpy(dtype="datetime64[ns]")
    meta = GameMeta(
        date="2026-03-23",
        match_id="m1",
        sport="nba",
        open_fav_price=open_fav,
        tipoff_fav_price=tipoff_fav,
        open_fav_token_id="tok_fav",
        can_settle=True,
        price_quality="ok",
        open_favorite_team=FAV,
    )
    scenario = Scenario(
        name="s",
        universe_filter=ComponentSpec(name="upper_strong"),
        side_target="favorite",
        trigger=ComponentSpec(name="dip_below_anchor",
                              params={"anchor": "open", "threshold_cents": 10}),
        exit=ComponentSpec(name="settlement"),
        lock=LockSpec(mode="sequential"),
        fee_model="taker",
    )
    return Context(
        trades_df=df,
        trades_time_array=time_arr,
        favorite_team=FAV,
        underdog_team=DOG,
        open_prices={FAV: open_fav, DOG: 1 - open_fav},
        tipoff_prices={FAV: tipoff_fav, DOG: 1 - tipoff_fav},
        tipoff_time=pd.Timestamp(tipoff),
        game_end=pd.Timestamp(game_end),
        game_meta=meta,
        scenario=scenario,
    )


@pytest.fixture
def base_time():
    return datetime(2026, 3, 23, 19, 30, 0)


@pytest.fixture
def game_times(base_time):
    return {"tipoff": base_time, "game_end": base_time + timedelta(hours=2, minutes=30)}


def _trades(rows):
    return pd.DataFrame(rows, columns=["datetime", "price", "team", "token_id"])


def test_basic_dip_hit(base_time, game_times):
    df = _trades([
        (base_time + timedelta(minutes=1), 0.92, FAV, "tok_fav"),
        (base_time + timedelta(minutes=2), 0.91, FAV, "tok_fav"),
        (base_time + timedelta(minutes=3), 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=4), 0.84, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    trig = dip_below_anchor(ctx, game_times["tipoff"],
                            {"anchor": "open", "threshold_cents": 10})
    assert trig is not None
    assert trig.trigger_price == 0.81
    assert trig.trigger_time == pd.Timestamp(base_time + timedelta(minutes=3))
    assert trig.team == FAV
    assert trig.anchor_price == 0.92
    assert trig.side == "yes"


def test_no_dip_returns_none(base_time, game_times):
    df = _trades([
        (base_time + timedelta(minutes=1), 0.92, FAV, "tok_fav"),
        (base_time + timedelta(minutes=2), 0.91, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    trig = dip_below_anchor(ctx, game_times["tipoff"],
                            {"anchor": "open", "threshold_cents": 20})
    assert trig is None


def test_empty_trades(base_time, game_times):
    df = _trades([])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    trig = dip_below_anchor(ctx, game_times["tipoff"],
                            {"anchor": "open", "threshold_cents": 10})
    assert trig is None


def test_ignores_pregame_and_other_team(base_time, game_times):
    df = _trades([
        (base_time - timedelta(minutes=15), 0.50, FAV, "tok_fav"),  # pregame dip
        (base_time + timedelta(minutes=1), 0.81, DOG, "tok_dog"),   # other team dip
        (base_time + timedelta(minutes=2), 0.91, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    trig = dip_below_anchor(ctx, game_times["tipoff"],
                            {"anchor": "open", "threshold_cents": 10})
    assert trig is None


def test_excludes_post_game(base_time, game_times):
    df = _trades([
        (base_time + timedelta(minutes=1), 0.91, FAV, "tok_fav"),
        (game_times["game_end"] + timedelta(minutes=5), 0.10, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    trig = dip_below_anchor(ctx, game_times["tipoff"],
                            {"anchor": "open", "threshold_cents": 10})
    assert trig is None


def test_anchor_tipoff(base_time, game_times):
    df = _trades([
        (base_time + timedelta(minutes=1), 0.79, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"],
                    open_fav=0.95, tipoff_fav=0.90)
    trig = dip_below_anchor(ctx, game_times["tipoff"],
                            {"anchor": "tipoff", "threshold_cents": 10})
    assert trig is not None
    assert trig.anchor_price == 0.90
    assert trig.trigger_price == 0.79


def test_unknown_anchor_raises(base_time, game_times):
    df = _trades([(base_time + timedelta(minutes=1), 0.81, FAV, "tok_fav")])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    with pytest.raises(ValueError, match="Unknown anchor"):
        dip_below_anchor(ctx, game_times["tipoff"],
                         {"anchor": "midnight", "threshold_cents": 10})


def test_registry_entry():
    from backtest import triggers as _  # noqa: F401
    assert TRIGGERS["dip_below_anchor"] is dip_below_anchor
