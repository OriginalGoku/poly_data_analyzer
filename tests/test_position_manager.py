"""Tests for backtest.position_manager.PositionManager."""
from __future__ import annotations

import warnings
from typing import List, Optional

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


def _trigger(t: pd.Timestamp, team: str = "AAA", price: float = 0.6) -> Trigger:
    return Trigger(
        trigger_time=t,
        trigger_price=price,
        team=team,
        token_id="tok-AAA",
        side="favorite",
    )


def _position(t: pd.Timestamp, idx: int, team: str = "AAA") -> Position:
    placeholder = Exit(
        exit_time=t,
        exit_price=0.0,
        exit_kind="placeholder",
        status="open",
    )
    return Position(
        trigger=_trigger(t, team=team),
        exit=placeholder,
        position_index_in_game=idx,
    )


def _ctx(trades: Optional[pd.DataFrame] = None) -> Context:
    if trades is None:
        trades = pd.DataFrame(
            {
                "datetime": [T0 + pd.Timedelta(seconds=i) for i in range(3)],
                "team": ["AAA", "AAA", "BBB"],
                "price": [0.55, 0.50, 0.45],
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
        name="test",
        universe_filter=ComponentSpec("any"),
        side_target="favorite",
        trigger=ComponentSpec("any"),
        exit=ComponentSpec("any"),
        lock=LockSpec(mode="sequential"),
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


class _ScannerSeq:
    """Returns predetermined Exit objects in order; None when exhausted."""

    def __init__(self, exits: List[Optional[Exit]]):
        self._exits = list(exits)
        self.calls = 0

    def __call__(self, ctx: Context, now: pd.Timestamp) -> Optional[Exit]:
        self.calls += 1
        if not self._exits:
            return None
        return self._exits.pop(0)


# ------------------- sequential tests -------------------


def test_sequential_single_open_blocks_second_register():
    pm = PositionManager(LockSpec(mode="sequential"))
    pos = _position(T0, 0)
    pm.register_position(pos, _ScannerSeq([None]))
    assert pm.open_count() == 1
    assert pm.can_open(T0 + pd.Timedelta(seconds=10)) is False


def test_sequential_cooldown_gates_reentry():
    pm = PositionManager(LockSpec(mode="sequential", cool_down_seconds=60))
    t1 = T0
    pm.register_position(_position(t1, 0), _ScannerSeq([None]))

    exit_t = t1 + pd.Timedelta(seconds=5)
    exit_obj = Exit(exit_time=exit_t, exit_price=0.5, exit_kind="profit", status="closed")
    # Tick that fires the exit.
    pm._slots[0].exit_scanner = _ScannerSeq([exit_obj])
    pm.tick(_ctx(), exit_t)

    assert pm.open_count() == 0
    # Within cool-down: blocked.
    assert pm.can_open(exit_t + pd.Timedelta(seconds=30)) is False
    # After cool-down: allowed.
    assert pm.can_open(exit_t + pd.Timedelta(seconds=60)) is True


def test_sequential_stop_loss_blocks_when_re_arm_disabled():
    pm = PositionManager(
        LockSpec(mode="sequential", allow_re_arm_after_stop_loss=False)
    )
    t1 = T0
    pm.register_position(_position(t1, 0), _ScannerSeq([None]))
    exit_t = t1 + pd.Timedelta(seconds=5)
    sl = Exit(exit_time=exit_t, exit_price=0.4, exit_kind="stop_loss", status="closed")
    pm._slots[0].exit_scanner = _ScannerSeq([sl])
    pm.tick(_ctx(), exit_t)

    # Forever blocked, even far in the future.
    assert pm.can_open(exit_t + pd.Timedelta(hours=2)) is False
    assert pm.exhausted() is True


def test_sequential_stop_loss_re_arm_allowed():
    pm = PositionManager(
        LockSpec(
            mode="sequential",
            cool_down_seconds=10,
            allow_re_arm_after_stop_loss=True,
        )
    )
    t1 = T0
    pm.register_position(_position(t1, 0), _ScannerSeq([None]))
    exit_t = t1 + pd.Timedelta(seconds=5)
    sl = Exit(exit_time=exit_t, exit_price=0.4, exit_kind="stop_loss", status="closed")
    pm._slots[0].exit_scanner = _ScannerSeq([sl])
    pm.tick(_ctx(), exit_t)

    assert pm.can_open(exit_t + pd.Timedelta(seconds=15)) is True
    assert pm.exhausted() is False


def test_sequential_next_eligible_time_returns_cooldown_end():
    pm = PositionManager(LockSpec(mode="sequential", cool_down_seconds=60))
    t1 = T0
    pm.register_position(_position(t1, 0), _ScannerSeq([None]))
    exit_t = t1 + pd.Timedelta(seconds=5)
    exit_obj = Exit(exit_time=exit_t, exit_price=0.5, exit_kind="profit", status="closed")
    pm._slots[0].exit_scanner = _ScannerSeq([exit_obj])
    pm.tick(_ctx(), exit_t)

    nxt = pm.next_eligible_time(exit_t + pd.Timedelta(seconds=10), GAME_END)
    assert nxt == exit_t + pd.Timedelta(seconds=60)


def test_sequential_next_eligible_clamps_to_game_end_when_blocked():
    pm = PositionManager(LockSpec(mode="sequential"))
    pm.register_position(_position(T0, 0), _ScannerSeq([None]))
    # Open, no exit predicted -> game_end.
    assert pm.next_eligible_time(T0 + pd.Timedelta(seconds=1), GAME_END) == GAME_END


# ------------------- scale_in tests -------------------


def test_scale_in_admits_up_to_max_entries():
    pm = PositionManager(LockSpec(mode="scale_in", max_entries=3, cool_down_seconds=0))
    for i in range(3):
        t = T0 + pd.Timedelta(seconds=i)
        assert pm.can_open(t) is True
        pm.register_position(_position(t, i), _ScannerSeq([None]))
    assert pm.total_entries() == 3
    assert pm.can_open(T0 + pd.Timedelta(seconds=10)) is False
    assert pm.open_count() == 3


def test_scale_in_min_spacing_via_cooldown():
    pm = PositionManager(
        LockSpec(mode="scale_in", max_entries=3, cool_down_seconds=30)
    )
    pm.register_position(_position(T0, 0), _ScannerSeq([None]))
    # Within spacing window: blocked.
    assert pm.can_open(T0 + pd.Timedelta(seconds=10)) is False
    # After spacing: allowed.
    assert pm.can_open(T0 + pd.Timedelta(seconds=30)) is True


def test_scale_in_warns_on_re_arm_flag():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        PositionManager(
            LockSpec(
                mode="scale_in",
                max_entries=2,
                allow_re_arm_after_stop_loss=True,
            )
        )
    assert any("ignored" in str(w.message).lower() for w in caught)


def test_scale_in_exhausted_when_cap_reached_and_all_closed():
    pm = PositionManager(LockSpec(mode="scale_in", max_entries=2, cool_down_seconds=0))
    for i in range(2):
        t = T0 + pd.Timedelta(seconds=i)
        pm.register_position(_position(t, i), _ScannerSeq([None]))
    assert pm.exhausted() is False  # still open
    # Close both via tick.
    for i, slot in enumerate(pm._slots):
        ext = Exit(
            exit_time=T0 + pd.Timedelta(seconds=10 + i),
            exit_price=0.5,
            exit_kind="profit",
            status="closed",
        )
        slot.exit_scanner = _ScannerSeq([ext])
    pm.tick(_ctx(), T0 + pd.Timedelta(seconds=20))
    assert pm.open_count() == 0
    assert pm.exhausted() is True


# ------------------- force_close_all tests -------------------


def test_force_close_all_uses_last_team_price():
    pm = PositionManager(LockSpec(mode="scale_in", max_entries=2, cool_down_seconds=0))
    pm.register_position(_position(T0, 0, team="AAA"), _ScannerSeq([None]))
    pm.register_position(_position(T0 + pd.Timedelta(seconds=1), 1, team="BBB"),
                         _ScannerSeq([None]))
    ctx = _ctx()
    pm.tick(ctx, T0 + pd.Timedelta(seconds=2))
    pm.force_close_all(GAME_END)
    closed = pm.closed_positions()
    assert len(closed) == 2
    by_team = {c.trigger.team: c for c in closed}
    assert by_team["AAA"].exit.exit_price == 0.50  # last AAA trade price in fixture
    assert by_team["BBB"].exit.exit_price == 0.45
    for p in closed:
        assert p.exit.exit_kind == "forced_close"
        assert p.exit.status == "forced_close"
        assert p.exit.exit_time == GAME_END


def test_force_close_all_falls_back_to_trigger_price_without_trades():
    pm = PositionManager(LockSpec(mode="sequential"))
    pos = _position(T0, 0, team="ZZZ")  # team not in trades
    pm.register_position(pos, _ScannerSeq([None]))
    ctx = _ctx()
    pm.tick(ctx, T0)
    pm.force_close_all(GAME_END)
    closed = pm.closed_positions()
    assert len(closed) == 1
    assert closed[0].exit.exit_price == pytest.approx(pos.trigger.trigger_price)


def test_force_close_all_skips_already_closed():
    pm = PositionManager(LockSpec(mode="sequential"))
    pos = _position(T0, 0)
    real_exit = Exit(
        exit_time=T0 + pd.Timedelta(seconds=5),
        exit_price=0.55,
        exit_kind="profit",
        status="closed",
    )
    pm.register_position(pos, _ScannerSeq([real_exit]))
    ctx = _ctx()
    pm.tick(ctx, T0 + pd.Timedelta(seconds=5))
    pm.force_close_all(GAME_END)
    closed = pm.closed_positions()
    assert len(closed) == 1
    assert closed[0].exit.exit_kind == "profit"  # not overwritten


# ------------------- guard rails -------------------


def test_register_when_blocked_raises():
    pm = PositionManager(LockSpec(mode="sequential"))
    pm.register_position(_position(T0, 0), _ScannerSeq([None]))
    with pytest.raises(RuntimeError):
        pm.register_position(_position(T0 + pd.Timedelta(seconds=1), 1),
                             _ScannerSeq([None]))


def test_unsupported_mode_raises():
    with pytest.raises(ValueError):
        PositionManager(LockSpec(mode="weird"))
