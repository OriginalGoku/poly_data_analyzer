"""Invariant: every Exit emitted by PositionManager has non-None exit_time.

This holds for both scanner-driven exits (rejected at tick time) and
forced-close synthesised exits.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import pytest

from backtest.contracts import (
    ComponentSpec,
    Context,
    Exit,
    GameMeta,
    LockSpec,
    Position,
    Scenario,
    Trigger,
)
from backtest.position_manager import PositionManager


T0 = pd.Timestamp("2025-01-01 18:00:00", tz="UTC")
GAME_END = T0 + pd.Timedelta(hours=3)


def _make_ctx() -> Context:
    trades = pd.DataFrame(
        {
            "datetime": [T0 + pd.Timedelta(seconds=i) for i in range(4)],
            "team": ["AAA", "BBB", "AAA", "BBB"],
            "price": [0.6, 0.4, 0.55, 0.45],
        }
    )
    arr = np.array(trades["datetime"].values, dtype="datetime64[ns]")
    meta = GameMeta(
        date="2025-01-01",
        match_id="m1",
        sport="nba",
        open_fav_price=0.6,
        tipoff_fav_price=0.6,
        open_fav_token_id="tok-AAA",
        can_settle=True,
        price_quality="good",
        open_favorite_team="AAA",
    )
    scen = Scenario(
        name="t",
        universe_filter=ComponentSpec("any"),
        side_target="favorite",
        trigger=ComponentSpec("any"),
        exit=ComponentSpec("any"),
        lock=LockSpec(mode="scale_in", max_entries=4),
        fee_model="default",
    )
    return Context(
        trades_df=trades,
        trades_time_array=arr,
        favorite_team="AAA",
        underdog_team="BBB",
        open_prices={"AAA": 0.6, "BBB": 0.4},
        tipoff_prices={"AAA": 0.6, "BBB": 0.4},
        tipoff_time=T0,
        game_end=GAME_END,
        game_meta=meta,
        scenario=scen,
    )


def _position(t: pd.Timestamp, idx: int, team: str) -> Position:
    placeholder = Exit(exit_time=t, exit_price=0.0, exit_kind="placeholder", status="open")
    trig = Trigger(
        trigger_time=t,
        trigger_price=0.6,
        team=team,
        token_id=f"tok-{team}",
        side="favorite",
    )
    return Position(trigger=trig, exit=placeholder, position_index_in_game=idx)


def _scanner_returning(exit_obj: Optional[Exit]):
    def scan(ctx: Context, now: pd.Timestamp) -> Optional[Exit]:
        return exit_obj
    return scan


def test_forced_close_exits_have_non_none_exit_time():
    pm = PositionManager(LockSpec(mode="scale_in", max_entries=4, cool_down_seconds=0))
    teams = ["AAA", "BBB", "AAA", "BBB"]
    for i, tm in enumerate(teams):
        t = T0 + pd.Timedelta(seconds=i)
        pm.register_position(_position(t, i, tm), _scanner_returning(None))
    ctx = _make_ctx()
    pm.tick(ctx, T0 + pd.Timedelta(seconds=10))
    pm.force_close_all(GAME_END)

    closed = pm.closed_positions()
    assert len(closed) == 4
    for p in closed:
        assert p.exit.exit_time is not None
        assert p.exit.exit_kind == "forced_close"
        assert p.exit.status == "forced_close"


def test_scanner_exit_with_none_exit_time_rejected():
    pm = PositionManager(LockSpec(mode="sequential"))
    pm.register_position(_position(T0, 0, "AAA"), _scanner_returning(
        Exit(exit_time=None, exit_price=0.5, exit_kind="profit", status="closed")
    ))
    with pytest.raises(ValueError):
        pm.tick(_make_ctx(), T0 + pd.Timedelta(seconds=1))


def test_mixed_scanner_and_forced_close_all_have_exit_time():
    pm = PositionManager(LockSpec(mode="scale_in", max_entries=3, cool_down_seconds=0))
    pm.register_position(_position(T0, 0, "AAA"), _scanner_returning(
        Exit(exit_time=T0 + pd.Timedelta(seconds=2), exit_price=0.55,
             exit_kind="profit", status="closed")
    ))
    pm.register_position(_position(T0 + pd.Timedelta(seconds=1), 1, "BBB"),
                         _scanner_returning(None))
    pm.register_position(_position(T0 + pd.Timedelta(seconds=2), 2, "AAA"),
                         _scanner_returning(None))
    ctx = _make_ctx()
    pm.tick(ctx, T0 + pd.Timedelta(seconds=5))
    pm.force_close_all(GAME_END)

    closed = pm.closed_positions()
    assert len(closed) == 3
    for p in closed:
        assert p.exit.exit_time is not None
