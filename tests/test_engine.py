"""Tests for backtest.engine.run_scenario_on_game."""
from __future__ import annotations

from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd
import pytest

from backtest.contracts import (
    ComponentSpec,
    Context,
    Exit,
    GameMeta,
    LockSpec,
    Scenario,
    Trigger,
)
from backtest.engine import fee_pct_for, run_scenario_on_game
from backtest.registry import EXITS, TRIGGERS


T0 = pd.Timestamp("2025-01-01 18:00:00", tz="UTC")
GAME_END = T0 + pd.Timedelta(hours=3)


def _build_ctx(scenario: Scenario, trades: Optional[pd.DataFrame] = None) -> Context:
    if trades is None:
        rows = [
            {"datetime": T0 + pd.Timedelta(seconds=i * 10), "team": "AAA", "price": 0.6 - i * 0.01}
            for i in range(20)
        ]
        trades = pd.DataFrame(rows)
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
        scenario=scenario,
        settings={},
    )


def _scenario(
    name: str,
    lock: LockSpec,
    trigger_name: str,
    exit_name: str,
    trigger_params: Mapping[str, Any] = None,
    exit_params: Mapping[str, Any] = None,
) -> Scenario:
    return Scenario(
        name=name,
        universe_filter=ComponentSpec("any"),
        side_target="favorite",
        trigger=ComponentSpec(trigger_name, dict(trigger_params or {})),
        exit=ComponentSpec(exit_name, dict(exit_params or {})),
        lock=lock,
        fee_model="taker",
    )


@pytest.fixture
def register_components():
    """Allows tests to register triggers/exits and clean up after.

    Saves any pre-existing entry so overwriting (e.g. real ``reversion_to_open``)
    is restored, not removed.
    """
    saved_triggers: dict[str, Any] = {}
    saved_exits: dict[str, Any] = {}
    added_triggers: list[str] = []
    added_exits: list[str] = []

    _MISSING = object()

    def _add_trigger(name, fn):
        if name not in saved_triggers:
            saved_triggers[name] = TRIGGERS.get(name, _MISSING)
        TRIGGERS[name] = fn
        added_triggers.append(name)

    def _add_exit(name, fn):
        if name not in saved_exits:
            saved_exits[name] = EXITS.get(name, _MISSING)
        EXITS[name] = fn
        added_exits.append(name)

    yield _add_trigger, _add_exit

    for n in added_triggers:
        prev = saved_triggers.get(n, _MISSING)
        if prev is _MISSING:
            TRIGGERS.pop(n, None)
        else:
            TRIGGERS[n] = prev
    for n in added_exits:
        prev = saved_exits.get(n, _MISSING)
        if prev is _MISSING:
            EXITS.pop(n, None)
        else:
            EXITS[n] = prev


def _every_5s_trigger(ctx: Context, after_time, params):
    """Fires on the next AAA trade strictly after `after_time`."""
    sliced = ctx.slice_after(after_time, team="AAA")
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
        team="AAA",
        token_id="tok-AAA",
        side="favorite",
    )


def _noop_exit_factory(ctx, trigger, params):
    """Exit scanner that never fires; engine force-closes at game_end."""

    def scan(ctx_, now):
        return None

    return scan


def _quick_exit_factory(ctx, trigger, params):
    """Exit scanner that returns an Exit `delay_seconds` after the trigger.

    Like real exit scanners, returns the exit immediately when ticked — the
    exit_time is the future trade time at which the condition resolves.
    """
    delay = pd.Timedelta(seconds=params.get("delay_seconds", 30))
    exit_time = trigger.trigger_time + delay

    def scan(ctx_, now):
        if ctx_.game_end is not None and exit_time >= ctx_.game_end:
            return None
        return Exit(
            exit_time=exit_time,
            exit_price=float(trigger.trigger_price),
            exit_kind="take_profit",
            status="closed",
        )

    return scan


def test_sequential_blocks_until_exit(register_components):
    add_trigger, add_exit = register_components
    add_trigger("test_every", _every_5s_trigger)
    add_exit("test_quick", _quick_exit_factory)

    lock = LockSpec(mode="sequential", max_entries=1, cool_down_seconds=0.0)
    scen = _scenario(
        "seq",
        lock,
        "test_every",
        "test_quick",
        exit_params={"delay_seconds": 30},
    )
    ctx = _build_ctx(scen)
    positions = run_scenario_on_game(scen, ctx)

    # In sequential mode with always-firing trigger: at each cursor, register one
    # position; PM blocks new entries until that exit fires; trigger eventually
    # exhausts trades. We expect at least 2 entries (since exits fire ~30s later
    # and there are 20 trades over ~190s).
    assert len(positions) >= 2
    # All but possibly the last entry should be cleanly closed (not forced).
    closed = [p for p in positions if p.exit.exit_kind != "open"]
    assert len(closed) == len(positions)
    # position_index_in_game is 0,1,2,...
    assert [p.position_index_in_game for p in positions] == list(range(len(positions)))
    # Sequential: no two positions overlap in time.
    sorted_positions = sorted(positions, key=lambda p: p.trigger.trigger_time)
    for prev, nxt in zip(sorted_positions, sorted_positions[1:]):
        assert nxt.trigger.trigger_time >= prev.exit.exit_time


def test_scale_in_concurrent(register_components):
    add_trigger, add_exit = register_components
    add_trigger("test_every", _every_5s_trigger)
    add_exit("test_noop", _noop_exit_factory)

    lock = LockSpec(mode="scale_in", max_entries=3, cool_down_seconds=0.0)
    scen = _scenario("scale", lock, "test_every", "test_noop")
    ctx = _build_ctx(scen)
    positions = run_scenario_on_game(scen, ctx)

    assert len(positions) == 3
    # All forced-closed at game_end since exit never fires.
    for p in positions:
        assert p.exit.exit_kind == "forced_close"
        assert p.exit.exit_time == GAME_END
    assert [p.position_index_in_game for p in positions] == [0, 1, 2]


def test_forced_close_populates_remaining(register_components):
    add_trigger, add_exit = register_components
    add_trigger("test_every", _every_5s_trigger)
    add_exit("test_noop", _noop_exit_factory)

    lock = LockSpec(mode="sequential", max_entries=1, cool_down_seconds=0.0)
    scen = _scenario("forced", lock, "test_every", "test_noop")
    ctx = _build_ctx(scen)
    positions = run_scenario_on_game(scen, ctx)

    assert len(positions) == 1
    p = positions[0]
    assert p.exit.exit_kind == "forced_close"
    assert p.exit.exit_time == GAME_END
    # Settlement populated.
    assert p.settlement is not None
    assert "pnl" in p.settlement


def test_position_index_increments(register_components):
    add_trigger, add_exit = register_components
    add_trigger("test_every", _every_5s_trigger)
    add_exit("test_noop", _noop_exit_factory)

    lock = LockSpec(mode="scale_in", max_entries=5, cool_down_seconds=0.0)
    scen = _scenario("idx", lock, "test_every", "test_noop")
    ctx = _build_ctx(scen)
    positions = run_scenario_on_game(scen, ctx)

    indices = [p.position_index_in_game for p in positions]
    assert indices == list(range(len(positions)))


def test_trigger_returns_none_breaks_loop(register_components):
    add_trigger, add_exit = register_components

    call_count = {"n": 0}

    def _one_shot_trigger(ctx, after_time, params):
        if call_count["n"] == 0:
            call_count["n"] += 1
            return Trigger(
                trigger_time=T0 + pd.Timedelta(seconds=5),
                trigger_price=0.55,
                team="AAA",
                token_id="tok-AAA",
                side="favorite",
            )
        return None

    add_trigger("test_one_shot", _one_shot_trigger)
    add_exit("test_noop", _noop_exit_factory)

    lock = LockSpec(mode="scale_in", max_entries=10, cool_down_seconds=0.0)
    scen = _scenario("one", lock, "test_one_shot", "test_noop")
    ctx = _build_ctx(scen)
    positions = run_scenario_on_game(scen, ctx)

    assert len(positions) == 1


# ------------------- fee_pct_for + early-return tests -------------------


def test_fee_pct_for_default_taker():
    assert fee_pct_for("taker") == pytest.approx(0.002)


def test_fee_pct_for_default_maker():
    assert fee_pct_for("maker") == pytest.approx(0.0)


def test_fee_pct_for_unknown_model_raises():
    with pytest.raises(ValueError, match="Unknown fee_model"):
        fee_pct_for("not_a_model")


def test_fee_pct_for_settings_keyed_override():
    assert fee_pct_for("taker", {"fee_taker_pct": 0.005}) == pytest.approx(0.005)


def test_fee_pct_for_settings_fees_mapping():
    assert fee_pct_for("taker", {"fees": {"taker": 0.01}}) == pytest.approx(0.01)


def test_fee_pct_for_settings_allows_unknown_model_when_provided():
    assert fee_pct_for("custom", {"fee_custom_pct": 0.003}) == pytest.approx(0.003)


def test_run_scenario_returns_empty_when_no_tipoff(register_components):
    import dataclasses
    add_trigger, add_exit = register_components
    add_trigger("test_every", _every_5s_trigger)
    add_exit("test_noop", _noop_exit_factory)
    scen = _scenario(
        "no_tipoff", LockSpec(mode="sequential"), "test_every", "test_noop"
    )
    ctx = dataclasses.replace(_build_ctx(scen), tipoff_time=None)
    assert run_scenario_on_game(scen, ctx) == []


def test_run_scenario_returns_empty_when_no_game_end(register_components):
    import dataclasses
    add_trigger, add_exit = register_components
    add_trigger("test_every", _every_5s_trigger)
    add_exit("test_noop", _noop_exit_factory)
    scen = _scenario(
        "no_end", LockSpec(mode="sequential"), "test_every", "test_noop"
    )
    ctx = dataclasses.replace(_build_ctx(scen), game_end=None)
    assert run_scenario_on_game(scen, ctx) == []


# ------------------- regression: ExitScanner __call__ + final tick -------------------


def test_sequential_reversion_to_open_fires_before_game_end(register_components):
    """Regression for the two engine fixes:

    1. ExitScanner exposes __call__ so PositionManager (which calls
       slot.exit_scanner(ctx, now)) works with real exit factories.
    2. Engine runs pm.tick(ctx, game_end) before force_close_all so a
       scanner-driven exit (here reversion_to_open) gets a chance to fire on
       trades up to game_end and the position exits cleanly rather than
       being force-closed.
    """
    import backtest.exits  # registers reversion_to_open  # noqa: F401
    from backtest.exits.reversion_to_open import reversion_to_open

    open_fav = 0.6
    # Tape: a dip below open at +30s (entry), then prices recover above open
    # before game_end. With sequential lock, the position must close via
    # reversion (not forced_close).
    rows = []
    rows.append({"datetime": T0 + pd.Timedelta(seconds=30), "team": "AAA",
                 "price": 0.50, "token_id": "tok-AAA"})
    rows.append({"datetime": T0 + pd.Timedelta(seconds=120), "team": "AAA",
                 "price": 0.55, "token_id": "tok-AAA"})
    # Recovery trade well before game_end:
    rows.append({"datetime": T0 + pd.Timedelta(seconds=600), "team": "AAA",
                 "price": open_fav, "token_id": "tok-AAA"})
    trades = pd.DataFrame(rows)

    def _one_dip_trigger(ctx, after_time, params):
        sliced = ctx.slice_after(after_time, team="AAA")
        if sliced.empty:
            return None
        row = sliced.iloc[0]
        if float(row["price"]) >= open_fav:
            return None
        return Trigger(
            trigger_time=row["datetime"],
            trigger_price=float(row["price"]),
            team="AAA",
            token_id="tok-AAA",
            side="favorite",
            anchor_price=open_fav,
        )

    add_trigger, add_exit = register_components
    add_trigger("test_one_dip", _one_dip_trigger)
    add_exit("reversion_to_open", reversion_to_open)

    lock = LockSpec(mode="sequential", max_entries=1, cool_down_seconds=0.0)
    scen = _scenario("rev_reg", lock, "test_one_dip", "reversion_to_open")
    ctx = _build_ctx(scen, trades=trades)
    positions = run_scenario_on_game(scen, ctx)

    assert len(positions) == 1
    p = positions[0]
    # Regression assertion: scanner-driven exit fires; NOT forced_close.
    assert p.exit.exit_kind == "reversion", (
        f"expected reversion exit, got {p.exit.exit_kind!r} "
        f"(likely engine final-tick or ExitScanner.__call__ regression)"
    )
    assert p.exit.status == "filled"
    assert p.exit.exit_price == pytest.approx(open_fav)
    assert p.exit.exit_time < GAME_END
