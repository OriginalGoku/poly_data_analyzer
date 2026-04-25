"""Tests for backtest.exits.settlement."""
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
from backtest.exits.settlement import settlement
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
        exit=ComponentSpec(name="settlement"),
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


@pytest.fixture
def base_time():
    return datetime(2026, 3, 23, 19, 30, 0)


def test_settlement_scan_always_returns_none(base_time):
    tipoff = base_time
    game_end = base_time + timedelta(hours=2)
    df = _trades([
        (base_time + timedelta(minutes=5), 0.81, FAV, "tok_fav"),
        (base_time + timedelta(minutes=10), 0.95, FAV, "tok_fav"),
    ])
    ctx = _make_ctx(df, tipoff, game_end)
    trigger = Trigger(
        trigger_time=pd.Timestamp(base_time + timedelta(minutes=5)),
        trigger_price=0.81, team=FAV, token_id="tok_fav", side="yes",
        anchor_price=0.92,
    )
    scanner = settlement(ctx, trigger, {})
    assert isinstance(scanner, ExitScanner)
    assert scanner.scan(ctx, game_end) is None
    assert scanner.scan(ctx, base_time + timedelta(minutes=20)) is None


def test_settlement_empty_post_trigger(base_time):
    tipoff = base_time
    game_end = base_time + timedelta(hours=2)
    df = _trades([])
    ctx = _make_ctx(df, tipoff, game_end)
    trigger = Trigger(
        trigger_time=pd.Timestamp(base_time + timedelta(minutes=5)),
        trigger_price=0.81, team=FAV, token_id="tok_fav", side="yes",
        anchor_price=0.92,
    )
    scanner = settlement(ctx, trigger, {})
    assert scanner.scan(ctx, game_end) is None


def test_registry_entry():
    from backtest import exits as _  # noqa: F401
    assert EXITS["settlement"] is settlement
