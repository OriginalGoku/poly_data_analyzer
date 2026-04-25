"""Tests for backtest.exits.tp_sl."""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from backtest.contracts import (
    ComponentSpec,
    Context,
    GameMeta,
    LockSpec,
    Scenario,
    Trigger,
)
from backtest.exits import ExitScanner
from backtest.exits.tp_sl import tp_sl
from backtest.registry import EXITS

FAV = "FAV"
DOG = "DOG"


def _make_ctx(trades_df: pd.DataFrame, tipoff: datetime, game_end: datetime,
              open_fav: float = 0.92) -> Context:
    df = trades_df.sort_values("datetime").reset_index(drop=True) if not trades_df.empty else trades_df
    time_arr = (df["datetime"].to_numpy(dtype="datetime64[ns]")
                if not df.empty else pd.to_datetime([]).to_numpy(dtype="datetime64[ns]"))
    meta = GameMeta(
        date="2026-03-23", match_id="m1", sport="nba",
        open_fav_price=open_fav, tipoff_fav_price=open_fav,
        open_fav_token_id="tok_fav", can_settle=True,
        price_quality="ok", open_favorite_team=FAV,
    )
    scenario = Scenario(
        name="s",
        universe_filter=ComponentSpec(name="upper_strong"),
        side_target="favorite",
        trigger=ComponentSpec(name="dip_below_anchor", params={"anchor": "open", "threshold_cents": 10}),
        exit=ComponentSpec(name="tp_sl", params={"take_profit_cents": 3, "stop_loss_cents": 5}),
        lock=LockSpec(mode="sequential"),
        fee_model="taker",
    )
    return Context(
        trades_df=df, trades_time_array=time_arr,
        favorite_team=FAV, underdog_team=DOG,
        open_prices={FAV: open_fav, DOG: 1 - open_fav},
        tipoff_prices={FAV: open_fav, DOG: 1 - open_fav},
        tipoff_time=pd.Timestamp(tipoff), game_end=pd.Timestamp(game_end),
        game_meta=meta, scenario=scenario,
    )


def _trades(rows):
    return pd.DataFrame(rows, columns=["datetime", "price", "team", "token_id"])


def _trigger(t: datetime, price: float = 0.81) -> Trigger:
    return Trigger(
        trigger_time=pd.Timestamp(t), trigger_price=price,
        team=FAV, token_id="tok_fav", side="yes", anchor_price=0.92,
    )


@pytest.fixture
def base_time():
    return datetime(2026, 3, 23, 19, 30, 0)


def test_take_profit_first(base_time):
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=8), 0.83, FAV, "tok_fav"),
        (base_time + timedelta(minutes=10), 0.84, FAV, "tok_fav"),  # TP at 0.81+3c
        (base_time + timedelta(minutes=15), 0.78, FAV, "tok_fav"),  # would hit SL but TP first
    ])
    ctx = _make_ctx(df, base_time, game_end)
    params = {"take_profit_cents": 3, "stop_loss_cents": 5, "max_hold_seconds": 7200}
    scanner = tp_sl(ctx, _trigger(entry_t), params)
    assert isinstance(scanner, ExitScanner)
    ex = scanner.scan(ctx, game_end)
    assert ex is not None
    assert ex.exit_kind == "take_profit"
    assert ex.exit_price == 0.84
    assert ex.exit_time == pd.Timestamp(base_time + timedelta(minutes=10))


def test_stop_loss_first(base_time):
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=8), 0.78, FAV, "tok_fav"),
        (base_time + timedelta(minutes=10), 0.76, FAV, "tok_fav"),  # SL at 0.81-5c
        (base_time + timedelta(minutes=15), 0.85, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, base_time, game_end)
    params = {"take_profit_cents": 3, "stop_loss_cents": 5, "max_hold_seconds": 7200}
    ex = tp_sl(ctx, _trigger(entry_t), params).scan(ctx, game_end)
    assert ex is not None
    assert ex.exit_kind == "stop_loss"
    assert ex.exit_price == 0.76
    assert ex.exit_time == pd.Timestamp(base_time + timedelta(minutes=10))


def test_max_hold_first(base_time):
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=8), 0.82, FAV, "tok_fav"),
        (base_time + timedelta(minutes=12), 0.82, FAV, "tok_fav"),  # past deadline
        (base_time + timedelta(minutes=15), 0.84, FAV, "tok_fav"),  # TP but after max_hold
    ])
    ctx = _make_ctx(df, base_time, game_end)
    # deadline = entry_t + 360s = base+11min; trade at base+12min triggers max_hold
    params = {"take_profit_cents": 3, "stop_loss_cents": 5, "max_hold_seconds": 360}
    ex = tp_sl(ctx, _trigger(entry_t), params).scan(ctx, game_end)
    assert ex is not None
    assert ex.exit_kind == "max_hold"
    assert ex.exit_time == pd.Timestamp(base_time + timedelta(minutes=12))
    assert ex.exit_price == 0.82


def test_none_fire(base_time):
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=10), 0.82, FAV, "tok_fav"),
        (base_time + timedelta(minutes=20), 0.80, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, base_time, game_end)
    params = {"take_profit_cents": 5, "stop_loss_cents": 10, "max_hold_seconds": None}
    assert tp_sl(ctx, _trigger(entry_t), params).scan(ctx, game_end) is None


def test_simultaneous_tp_sl_tp_wins(base_time):
    # Misconfig: tp_cents negative-equiv (price >= tp AND price <= sl on same trade).
    # Construct via tp very loose and sl very tight overlap: entry 0.81,
    # tp_cents=-2 => tp=0.79 (any price >=0.79 hits TP); sl_cents=-3 => sl=0.84.
    # A trade at 0.82 satisfies tp>=0.79 AND sl<=0.84 simultaneously.
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=8), 0.82, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, base_time, game_end)
    params = {"take_profit_cents": -2, "stop_loss_cents": -3, "max_hold_seconds": None}
    with pytest.warns(UserWarning, match="both TP"):
        ex = tp_sl(ctx, _trigger(entry_t), params).scan(ctx, game_end)
    assert ex is not None
    assert ex.exit_kind == "take_profit"
    assert ex.exit_price == 0.82


def test_null_max_hold_no_deadline(base_time):
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=30), 0.82, FAV, "tok_fav"),  # would be past any short deadline
        (base_time + timedelta(minutes=60), 0.84, FAV, "tok_fav"),  # TP eventually
    ])
    ctx = _make_ctx(df, base_time, game_end)
    params = {"take_profit_cents": 3, "stop_loss_cents": 5, "max_hold_seconds": None}
    ex = tp_sl(ctx, _trigger(entry_t), params).scan(ctx, game_end)
    assert ex is not None
    assert ex.exit_kind == "take_profit"
    assert ex.exit_price == 0.84


def test_null_take_profit_sl_only(base_time):
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=8), 0.90, FAV, "tok_fav"),  # would hit TP if set
        (base_time + timedelta(minutes=12), 0.75, FAV, "tok_fav"),  # SL hit
    ])
    ctx = _make_ctx(df, base_time, game_end)
    params = {"take_profit_cents": None, "stop_loss_cents": 5, "max_hold_seconds": None}
    ex = tp_sl(ctx, _trigger(entry_t), params).scan(ctx, game_end)
    assert ex is not None
    assert ex.exit_kind == "stop_loss"
    assert ex.exit_price == 0.75


def test_excludes_other_team(base_time):
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=8), 0.84, DOG, "tok_dog"),  # other team — ignored
        (base_time + timedelta(minutes=15), 0.83, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, base_time, game_end)
    params = {"take_profit_cents": 3, "stop_loss_cents": 5, "max_hold_seconds": None}
    assert tp_sl(ctx, _trigger(entry_t), params).scan(ctx, game_end) is None


def test_registry_entry():
    from backtest import exits as _  # noqa: F401
    assert EXITS["tp_sl"] is tp_sl
