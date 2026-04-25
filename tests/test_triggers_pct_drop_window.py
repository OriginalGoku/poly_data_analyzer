"""Tests for backtest.triggers.pct_drop_window."""
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
from backtest.registry import TRIGGERS
from backtest.triggers.pct_drop_window import pct_drop_window


FAV = "FAV"
DOG = "DOG"


def _make_ctx(
    trades_df: pd.DataFrame,
    tipoff: datetime,
    game_end: datetime,
    open_fav: float = 0.80,
    tipoff_fav: float = 0.80,
    side_target: str = "favorite",
) -> Context:
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
        side_target=side_target,
        trigger=ComponentSpec(name="pct_drop_window"),
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


def test_bounded_window_fires_inside(base_time, game_times):
    df = _trades([
        (base_time + timedelta(seconds=30), 0.30, FAV, "tok_fav"),  # before lo
        (base_time + timedelta(seconds=120), 0.35, FAV, "tok_fav"),  # inside
        (base_time + timedelta(seconds=400), 0.20, FAV, "tok_fav"),  # after hi
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    # anchor 0.80, drop 50% -> target 0.40. Window [60, 300).
    trig = pct_drop_window(
        ctx,
        game_times["tipoff"] - timedelta(minutes=10),
        {"anchor": "open", "drop_pct": 50.0,
         "window_seconds_after_tipoff": [60, 300]},
    )
    assert trig is not None
    assert trig.trigger_price == 0.35
    assert trig.team == FAV
    assert trig.anchor_price == 0.80
    assert trig.side == "yes"


def test_bounded_window_ignores_outside(base_time, game_times):
    df = _trades([
        (base_time + timedelta(seconds=30), 0.30, FAV, "tok_fav"),    # before lo
        (base_time + timedelta(seconds=400), 0.20, FAV, "tok_fav"),   # after hi
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    trig = pct_drop_window(
        ctx,
        game_times["tipoff"] - timedelta(minutes=10),
        {"anchor": "open", "drop_pct": 50.0,
         "window_seconds_after_tipoff": [60, 300]},
    )
    assert trig is None


def test_unbounded_window(base_time, game_times):
    df = _trades([
        (base_time + timedelta(seconds=30), 0.50, FAV, "tok_fav"),
        (base_time + timedelta(seconds=900), 0.39, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    trig = pct_drop_window(
        ctx,
        game_times["tipoff"] - timedelta(minutes=10),
        {"anchor": "open", "drop_pct": 50.0,
         "window_seconds_after_tipoff": None},
    )
    assert trig is not None
    assert trig.trigger_price == 0.39


def test_anchor_tipoff_switch(base_time, game_times):
    df = _trades([
        (base_time + timedelta(seconds=120), 0.44, FAV, "tok_fav"),
    ])
    # open=0.95, tipoff=0.90. drop_pct=50 -> open target 0.475 (hit), tipoff target 0.45 (hit).
    # Use tipoff anchor.
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"],
                    open_fav=0.95, tipoff_fav=0.90)
    trig = pct_drop_window(
        ctx,
        game_times["tipoff"] - timedelta(minutes=10),
        {"anchor": "tipoff", "drop_pct": 50.0,
         "window_seconds_after_tipoff": [0, 600]},
    )
    assert trig is not None
    assert trig.anchor_price == 0.90
    assert trig.trigger_price == 0.44


def test_never_fires(base_time, game_times):
    df = _trades([
        (base_time + timedelta(seconds=120), 0.50, FAV, "tok_fav"),
        (base_time + timedelta(seconds=180), 0.45, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    # target = 0.40, no trade <= 0.40
    trig = pct_drop_window(
        ctx,
        game_times["tipoff"] - timedelta(minutes=10),
        {"anchor": "open", "drop_pct": 50.0,
         "window_seconds_after_tipoff": [0, 600]},
    )
    assert trig is None


def test_window_bounds_inclusive_lower_exclusive_upper(base_time, game_times):
    df = _trades([
        (base_time + timedelta(seconds=60), 0.30, FAV, "tok_fav"),   # exactly lo -> include
        (base_time + timedelta(seconds=300), 0.20, FAV, "tok_fav"),  # exactly hi -> exclude
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    trig = pct_drop_window(
        ctx,
        game_times["tipoff"] - timedelta(minutes=10),
        {"anchor": "open", "drop_pct": 50.0,
         "window_seconds_after_tipoff": [60, 300]},
    )
    assert trig is not None
    assert trig.trigger_price == 0.30
    assert trig.trigger_time == pd.Timestamp(base_time + timedelta(seconds=60))


def test_underdog_side_target(base_time, game_times):
    # FAV open 0.80, DOG open 0.20. side_target=underdog, drop 50% from DOG anchor 0.20 -> target 0.10.
    df = _trades([
        (base_time + timedelta(seconds=120), 0.09, DOG, "tok_dog"),
        (base_time + timedelta(seconds=130), 0.08, FAV, "tok_fav"),  # wrong team
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"],
                    side_target="underdog")
    trig = pct_drop_window(
        ctx,
        game_times["tipoff"] - timedelta(minutes=10),
        {"anchor": "open", "drop_pct": 50.0,
         "window_seconds_after_tipoff": [0, 600]},
    )
    assert trig is not None
    assert trig.team == DOG
    assert trig.trigger_price == 0.09
    assert trig.anchor_price == pytest.approx(0.20)


def test_excludes_post_game(base_time, game_times):
    df = _trades([
        (game_times["game_end"] + timedelta(seconds=10), 0.10, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    trig = pct_drop_window(
        ctx,
        game_times["tipoff"] - timedelta(minutes=10),
        {"anchor": "open", "drop_pct": 50.0,
         "window_seconds_after_tipoff": None},
    )
    assert trig is None


def test_unknown_anchor_raises(base_time, game_times):
    df = _trades([(base_time + timedelta(seconds=120), 0.30, FAV, "tok_fav")])
    ctx = _make_ctx(df, game_times["tipoff"], game_times["game_end"])
    with pytest.raises(ValueError, match="Unknown anchor"):
        pct_drop_window(
            ctx,
            game_times["tipoff"] - timedelta(minutes=10),
            {"anchor": "midnight", "drop_pct": 50.0,
             "window_seconds_after_tipoff": None},
        )


def test_registry_entry():
    from backtest import triggers as _  # noqa: F401
    assert TRIGGERS["pct_drop_window"] is pct_drop_window
    # Sibling not removed.
    assert "dip_below_anchor" in TRIGGERS
