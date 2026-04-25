"""Tests for backtest.runner.run — grid orchestration + per-position output."""
from __future__ import annotations

from datetime import datetime
from typing import List, Mapping, Optional

import numpy as np
import pandas as pd
import pytest

from backtest import runner
from backtest.contracts import (
    ComponentSpec,
    Context,
    GameMeta,
    LockSpec,
    Scenario,
    Trigger,
)
from backtest.registry import EXITS, TRIGGERS, UNIVERSE_FILTERS


T0 = pd.Timestamp("2025-03-01 18:00:00", tz="UTC")
GAME_END = T0 + pd.Timedelta(hours=3)


@pytest.fixture
def register_components():
    """Register temporary triggers/exits/universe filters; clean up after."""
    added_t: list[str] = []
    added_e: list[str] = []
    added_u: list[str] = []

    def add_trigger(name, fn):
        TRIGGERS[name] = fn
        added_t.append(name)

    def add_exit(name, fn):
        EXITS[name] = fn
        added_e.append(name)

    def add_universe(name, fn):
        UNIVERSE_FILTERS[name] = fn
        added_u.append(name)

    yield add_trigger, add_exit, add_universe

    for n in added_t:
        TRIGGERS.pop(n, None)
    for n in added_e:
        EXITS.pop(n, None)
    for n in added_u:
        UNIVERSE_FILTERS.pop(n, None)


def _make_game_meta(date: str, match_id: str) -> GameMeta:
    return GameMeta(
        date=date,
        match_id=match_id,
        sport="nba",
        open_fav_price=0.7,
        tipoff_fav_price=0.7,
        open_fav_token_id=f"tok-{match_id}-AAA",
        can_settle=True,
        price_quality="good",
        open_favorite_team="AAA",
    )


def _make_trades(start: pd.Timestamp, count: int = 30) -> pd.DataFrame:
    rows = []
    for i in range(count):
        # Favorite (AAA) drops then rises; underdog (BBB) is the inverse.
        price_aaa = max(0.40, 0.70 - i * 0.01)
        rows.append(
            {
                "datetime": start + pd.Timedelta(seconds=10 * i),
                "team": "AAA",
                "price": price_aaa,
                "asset": "tok-AAA",
                "size": 100.0,
            }
        )
        rows.append(
            {
                "datetime": start + pd.Timedelta(seconds=10 * i + 1),
                "team": "BBB",
                "price": 1.0 - price_aaa,
                "asset": "tok-BBB",
                "size": 100.0,
            }
        )
    return pd.DataFrame(rows).sort_values("datetime").reset_index(drop=True)


def _build_context(
    game_meta: GameMeta,
    scenario: Scenario,
    data_dir: str,
    settings: Mapping[str, object],
) -> Context:
    trades = _make_trades(T0, count=30)
    arr = np.array(trades["datetime"].values, dtype="datetime64[ns]")
    manifest = {
        "away_team": "AAA",
        "home_team": "BBB",
        "token_ids": ["tok-AAA", "tok-BBB"],
    }
    events = [
        {
            "period": 4,
            "away_score": 110,
            "home_score": 100,
            "time_actual_dt": T0 + pd.Timedelta(hours=2),
        }
    ]
    ctx_settings = dict(settings)
    ctx_settings["manifest"] = manifest
    ctx_settings["events"] = events
    return Context(
        trades_df=trades,
        trades_time_array=arr,
        favorite_team="AAA",
        underdog_team="BBB",
        open_prices={"AAA": 0.7, "BBB": 0.3},
        tipoff_prices={"AAA": 0.7, "BBB": 0.3},
        tipoff_time=T0,
        game_end=GAME_END,
        game_meta=game_meta,
        scenario=scenario,
        settings=ctx_settings,
    )


def _one_shot_trigger_factory(team: str = "AAA"):
    def _trigger(ctx: Context, after_time, params) -> Optional[Trigger]:
        sliced = ctx.slice_after(after_time, team=team)
        if sliced.empty:
            return None
        if ctx.game_end is not None:
            sliced = sliced[sliced["datetime"] < ctx.game_end]
            if sliced.empty:
                return None
        # Honor sweep param if present so engine sees a different trigger
        # on each scenario; ensures sweep axis is observable in output.
        threshold = params.get("threshold_cents", 0)
        anchor = ctx.open_prices[team]
        target = anchor - threshold / 100.0
        hits = sliced[sliced["price"] <= target]
        if hits.empty:
            return None
        row = hits.iloc[0]
        return Trigger(
            trigger_time=row["datetime"],
            trigger_price=float(row["price"]),
            team=team,
            token_id=f"tok-{team}",
            side="yes",
            anchor_price=float(anchor),
        )

    return _trigger


def _noop_exit_factory(ctx, trigger, params):
    """Closure-style exit scanner that never fires (engine force-closes at game_end)."""

    def scan(ctx_, now):
        return None

    return scan


def _scenario(name: str, trigger_name: str, threshold_cents: int, sweep: bool = True) -> Scenario:
    return Scenario(
        name=name,
        universe_filter=ComponentSpec("test_uni", {}),
        side_target="favorite",
        trigger=ComponentSpec(trigger_name, {"threshold_cents": threshold_cents}),
        exit=ComponentSpec("test_noop_exit", {}),
        lock=LockSpec(mode="sequential", max_entries=1, cool_down_seconds=0.0),
        fee_model="taker",
        sweep_axes={"trigger.params.threshold_cents": threshold_cents} if sweep else {},
    )


def test_run_grid_three_games_three_sweeps_produces_nine_positions(register_components):
    add_trigger, add_exit, add_universe = register_components
    add_trigger("test_dip", _one_shot_trigger_factory(team="AAA"))
    add_exit("test_noop_exit", _noop_exit_factory)

    games = [
        _make_game_meta("2025-03-01", "g1"),
        _make_game_meta("2025-03-02", "g2"),
        _make_game_meta("2025-03-03", "g3"),
    ]
    add_universe("test_uni", lambda s, e, p: list(games))

    scenarios = [
        _scenario("dip__threshold=10", "test_dip", 10),
        _scenario("dip__threshold=15", "test_dip", 15),
        _scenario("dip__threshold=20", "test_dip", 20),
    ]

    progress_calls: List[tuple] = []

    def progress(done, total, name):
        progress_calls.append((done, total, name))

    per_position_df, aggregation_df = runner.run(
        scenarios=scenarios,
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 3),
        data_dir="data",
        settings={},
        progress_callback=progress,
        context_builder=_build_context,
    )

    # 3 games × 3 scenarios × 1 trigger fires per (sequential lock, settlement exit) = 9 rows.
    assert len(per_position_df) == 9
    assert len(aggregation_df) == 3

    expected_cols = {
        "scenario_name",
        "sweep_axis_trigger.params.threshold_cents",
        "date",
        "match_id",
        "sport",
        "side",
        "entry_team",
        "entry_token_id",
        "entry_time",
        "entry_price",
        "exit_time",
        "exit_price",
        "exit_kind",
        "status",
        "position_index_in_game",
        "settlement_payout",
        "pnl",
        "roi_pct",
        "hold_seconds",
        "max_drawdown_cents",
        "baseline_buy_at_open_roi",
        "baseline_buy_at_tipoff_roi",
        "baseline_buy_first_ingame_roi",
    }
    assert expected_cols.issubset(set(per_position_df.columns))

    # Sweep axis populated per row.
    sweep_col = "sweep_axis_trigger.params.threshold_cents"
    assert set(per_position_df[sweep_col].unique()) == {10, 15, 20}

    # Aggregation has one row per (scenario, sweep axis).
    agg_required = {
        "scenario_name",
        "sweep_axis_trigger.params.threshold_cents",
        "count",
        "mean_roi_pct",
        "win_rate",
        "mean_hold_seconds",
        "mean_drawdown_cents",
        "forced_close_count",
    }
    assert agg_required.issubset(set(aggregation_df.columns))
    assert (aggregation_df["count"] == 3).all()

    # Favorite-side baselines are populated (not NaN) for all rows.
    assert per_position_df["baseline_buy_at_open_roi"].notna().all()
    assert per_position_df["baseline_buy_at_tipoff_roi"].notna().all()
    assert per_position_df["baseline_buy_first_ingame_roi"].notna().all()

    # progress_callback called once per scenario.
    assert len(progress_calls) == 3
    assert progress_calls[-1][0] == 3 and progress_calls[-1][1] == 3


def test_run_empty_universe_returns_empty_dataframes(register_components):
    add_trigger, add_exit, add_universe = register_components
    add_trigger("test_dip", _one_shot_trigger_factory(team="AAA"))
    add_exit("test_noop_exit", _noop_exit_factory)
    add_universe("test_uni", lambda s, e, p: [])

    scenarios = [_scenario("only", "test_dip", 10)]
    per_position_df, aggregation_df = runner.run(
        scenarios=scenarios,
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 3),
        data_dir="data",
        settings={},
        context_builder=_build_context,
    )
    assert per_position_df.empty
    assert aggregation_df.empty


def test_universe_cached_across_scenarios(register_components):
    add_trigger, add_exit, add_universe = register_components
    add_trigger("test_dip", _one_shot_trigger_factory(team="AAA"))
    add_exit("test_noop_exit", _noop_exit_factory)

    call_counter = {"n": 0}
    games = [_make_game_meta("2025-03-01", "g1")]

    def filter_fn(s, e, p):
        call_counter["n"] += 1
        return list(games)

    add_universe("test_uni", filter_fn)
    scenarios = [
        _scenario("a", "test_dip", 10),
        _scenario("b", "test_dip", 15),
        _scenario("c", "test_dip", 20),
    ]
    runner.run(
        scenarios=scenarios,
        start_date=datetime(2025, 3, 1),
        end_date=datetime(2025, 3, 1),
        data_dir="data",
        settings={},
        context_builder=_build_context,
    )
    # Same universe_filter spec → cached once.
    assert call_counter["n"] == 1
