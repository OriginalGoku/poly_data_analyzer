"""Tests for Context.slice_after cursor mechanics + perf shape."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from backtest.contracts import (
    ComponentSpec,
    Context,
    GameMeta,
    LockSpec,
    Scenario,
)


T0 = pd.Timestamp("2025-01-01 18:00:00", tz="UTC")


def _ctx_from_trades(trades: pd.DataFrame) -> Context:
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
        name="cursor",
        universe_filter=ComponentSpec("any"),
        side_target="favorite",
        trigger=ComponentSpec("any"),
        exit=ComponentSpec("any"),
        lock=LockSpec(mode="sequential"),
        fee_model="taker",
    )
    return Context(
        trades_df=trades,
        trades_time_array=arr,
        favorite_team="AAA",
        underdog_team="BBB",
        open_prices={"AAA": 0.6},
        tipoff_prices={"AAA": 0.6},
        tipoff_time=T0,
        game_end=T0 + pd.Timedelta(hours=3),
        game_meta=meta,
        scenario=scen,
        settings={},
    )


def test_slice_after_strict_inequality():
    times = [T0 + pd.Timedelta(seconds=i) for i in range(5)]
    trades = pd.DataFrame({"datetime": times, "team": ["AAA"] * 5, "price": [0.5] * 5})
    ctx = _ctx_from_trades(trades)

    # slice_after(t) returns rows with timestamp strictly greater than t.
    sliced = ctx.slice_after(times[0])
    assert len(sliced) == 4
    assert sliced.iloc[0]["datetime"] == times[1]


def test_slice_after_before_first():
    times = [T0 + pd.Timedelta(seconds=i) for i in range(3)]
    trades = pd.DataFrame({"datetime": times, "team": ["AAA"] * 3, "price": [0.5] * 3})
    ctx = _ctx_from_trades(trades)
    sliced = ctx.slice_after(T0 - pd.Timedelta(seconds=1))
    assert len(sliced) == 3


def test_slice_after_after_last():
    times = [T0 + pd.Timedelta(seconds=i) for i in range(3)]
    trades = pd.DataFrame({"datetime": times, "team": ["AAA"] * 3, "price": [0.5] * 3})
    ctx = _ctx_from_trades(trades)
    sliced = ctx.slice_after(times[-1] + pd.Timedelta(seconds=1))
    assert sliced.empty


def test_slice_after_with_team_filter():
    times = [T0 + pd.Timedelta(seconds=i) for i in range(6)]
    trades = pd.DataFrame(
        {
            "datetime": times,
            "team": ["AAA", "BBB", "AAA", "BBB", "AAA", "BBB"],
            "price": [0.5] * 6,
        }
    )
    ctx = _ctx_from_trades(trades)
    sliced = ctx.slice_after(times[0], team="AAA")
    assert (sliced["team"] == "AAA").all()
    assert len(sliced) == 2  # indices 2, 4 (strictly after times[0])


def test_slice_after_perf_shape():
    """1000 sequential calls on a 100k-trade df should be well under 500ms."""
    n = 100_000
    times = pd.date_range(T0, periods=n, freq="100ms", tz="UTC")
    trades = pd.DataFrame(
        {"datetime": times, "team": ["AAA"] * n, "price": np.full(n, 0.5)}
    )
    ctx = _ctx_from_trades(trades)

    cursors = [times[i * (n // 1000)] for i in range(1000)]

    start = time.perf_counter()
    for c in cursors:
        ctx.slice_after(c)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5, f"slice_after too slow: {elapsed:.3f}s for 1000 calls on 100k rows"
