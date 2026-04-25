"""Tests for backtest.exits.reversion_to_open."""
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
from backtest.exits.reversion_to_open import reversion_to_open
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
        exit=ComponentSpec(name="reversion_to_open"),
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


def _trigger(t: datetime, price: float = 0.81, anchor: float = 0.92) -> Trigger:
    return Trigger(
        trigger_time=pd.Timestamp(t), trigger_price=price,
        team=FAV, token_id="tok_fav", side="yes", anchor_price=anchor,
    )


@pytest.fixture
def base_time():
    return datetime(2026, 3, 23, 19, 30, 0)


def test_first_trade_at_or_above_anchor(base_time):
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=10), 0.85, FAV, "tok_fav"),
        (base_time + timedelta(minutes=12), 0.92, FAV, "tok_fav"),  # hit
        (base_time + timedelta(minutes=15), 0.95, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, base_time, game_end)
    scanner = reversion_to_open(ctx, _trigger(entry_t), {})
    assert isinstance(scanner, ExitScanner)
    ex = scanner.scan(ctx, game_end)
    assert ex is not None
    assert ex.exit_price == 0.92
    assert ex.exit_time == pd.Timestamp(base_time + timedelta(minutes=12))
    assert ex.exit_kind == "reversion"
    assert ex.status == "filled"


def test_no_revert_returns_none(base_time):
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=10), 0.85, FAV, "tok_fav"),
        (base_time + timedelta(minutes=15), 0.88, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, base_time, game_end)
    scanner = reversion_to_open(ctx, _trigger(entry_t), {})
    assert scanner.scan(ctx, game_end) is None


def test_excludes_other_team(base_time):
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=10), 0.99, DOG, "tok_dog"),  # other team — ignore
        (base_time + timedelta(minutes=15), 0.85, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, base_time, game_end)
    scanner = reversion_to_open(ctx, _trigger(entry_t), {})
    assert scanner.scan(ctx, game_end) is None


def test_now_bound_excludes_late_hits(base_time):
    game_end = base_time + timedelta(hours=2)
    entry_t = base_time + timedelta(minutes=5)
    df = _trades([
        (entry_t, 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=30), 0.95, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, base_time, game_end)
    scanner = reversion_to_open(ctx, _trigger(entry_t), {})
    assert scanner.scan(ctx, base_time + timedelta(minutes=10)) is None
    ex = scanner.scan(ctx, game_end)
    assert ex is not None and ex.exit_price == 0.95


def test_registry_entry():
    from backtest import exits as _  # noqa: F401
    assert EXITS["reversion_to_open"] is reversion_to_open
