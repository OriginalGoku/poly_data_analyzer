"""Scenario grid runner.

Iterates a list of fully-concrete `Scenario` objects, resolves each scenario's
universe via `UNIVERSE_FILTERS`, builds a per-game `Context`, runs the engine,
and flattens the resulting `Position` objects into a per-position DataFrame.
Also aggregates by scenario + sweep axis.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Iterable, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

import loaders

from backtest.backtest_baselines import (
    baseline_buy_at_open,
    baseline_buy_at_tipoff,
    baseline_buy_first_ingame,
)
from backtest.contracts import Context, GameMeta, Position, Scenario
from backtest.engine import fee_pct_for, run_scenario_on_game
from backtest.registry import UNIVERSE_FILTERS

logger = logging.getLogger(__name__)


PER_POSITION_BASE_COLUMNS: Tuple[str, ...] = (
    "scenario_name",
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
)


def _default_load_game_context(
    game_meta: GameMeta,
    scenario: Scenario,
    data_dir: str,
    settings: Mapping[str, Any],
) -> Optional[Context]:
    """Load a real game and assemble a Context."""
    try:
        game = loaders.load_game(data_dir, game_meta.date, game_meta.match_id)
    except Exception as exc:
        logger.warning(
            "load_game failed for %s/%s: %s", game_meta.date, game_meta.match_id, exc
        )
        return None

    manifest = game["manifest"]
    trades_df = game["trades_df"].sort_values("datetime").reset_index(drop=True)
    events = game.get("events")

    tipoff_time = None
    if events:
        for ev in events:
            t = ev.get("time_actual_dt")
            if t is not None:
                tipoff_time = pd.Timestamp(t)
                break
    if tipoff_time is None and game.get("gamma_start") is not None:
        tipoff_time = pd.Timestamp(game["gamma_start"])
    game_end = (
        pd.Timestamp(game["gamma_closed"]) if game.get("gamma_closed") is not None else None
    )

    favorite_team = game_meta.open_favorite_team
    away = manifest.get("away_team")
    home = manifest.get("home_team")
    underdog_team = home if favorite_team == away else away

    open_prices = {
        favorite_team: float(game_meta.open_fav_price),
        underdog_team: 1.0 - float(game_meta.open_fav_price),
    }
    tipoff_prices = {
        favorite_team: float(game_meta.tipoff_fav_price),
        underdog_team: 1.0 - float(game_meta.tipoff_fav_price),
    }

    if not trades_df.empty:
        arr = np.array(trades_df["datetime"].values, dtype="datetime64[ns]")
    else:
        arr = np.array([], dtype="datetime64[ns]")

    ctx_settings = dict(settings)
    ctx_settings["manifest"] = manifest
    ctx_settings["events"] = events

    return Context(
        trades_df=trades_df,
        trades_time_array=arr,
        favorite_team=favorite_team,
        underdog_team=underdog_team,
        open_prices=open_prices,
        tipoff_prices=tipoff_prices,
        tipoff_time=tipoff_time,
        game_end=game_end,
        game_meta=game_meta,
        scenario=scenario,
        settings=ctx_settings,
    )


def _max_drawdown_cents(
    trades_df: pd.DataFrame,
    entry_team: str,
    entry_time: pd.Timestamp,
    exit_time: pd.Timestamp,
    entry_price: float,
) -> float:
    if trades_df is None or trades_df.empty:
        return 0.0
    if "team" not in trades_df.columns or "datetime" not in trades_df.columns:
        return 0.0
    sub = trades_df[
        (trades_df["team"] == entry_team)
        & (trades_df["datetime"] >= entry_time)
        & (trades_df["datetime"] <= exit_time)
    ]
    if sub.empty:
        return 0.0
    return float((entry_price - sub["price"].min()) * 100)


def _safe_fee_pct(fee_model: str, settings: Mapping[str, Any]) -> float:
    try:
        return fee_pct_for(fee_model, settings)
    except ValueError:
        return 0.0


def _baseline_roi(result: Mapping[str, Any]) -> float:
    if not result:
        return float("nan")
    if result.get("status") == "skipped_non_favorite":
        return float("nan")
    val = result.get("roi_pct")
    return float(val) if val is not None else float("nan")


def _build_row(
    scenario: Scenario,
    gm: GameMeta,
    ctx: Context,
    pos: Position,
    settings: Mapping[str, Any],
) -> dict:
    settlement = dict(pos.settlement) if pos.settlement else {}
    pnl_dict = settlement.get("pnl") or {}

    entry_time = pos.trigger.trigger_time
    exit_time = pos.exit.exit_time
    entry_price = float(pos.trigger.trigger_price)
    entry_team = pos.trigger.team

    side = scenario.side_target

    fee_pct = _safe_fee_pct(scenario.fee_model, ctx.settings)
    manifest = ctx.settings.get("manifest", {}) if isinstance(ctx.settings, Mapping) else {}
    events = ctx.settings.get("events") if isinstance(ctx.settings, Mapping) else None

    if side == "favorite":
        b_open = baseline_buy_at_open(
            open_price=ctx.open_prices.get(ctx.favorite_team),
            trades_df=ctx.trades_df,
            tipoff_time=ctx.tipoff_time,
            game_end=ctx.game_end,
            manifest=manifest,
            events=events,
            sport=gm.sport,
            fee_pct=fee_pct,
            settings=ctx.settings,
            entry_team=ctx.favorite_team,
            side="favorite",
            fee_model=scenario.fee_model if scenario.fee_model in ("taker", "maker") else "taker",
        )
        b_tip = baseline_buy_at_tipoff(
            tipoff_price=ctx.tipoff_prices.get(ctx.favorite_team),
            trades_df=ctx.trades_df,
            tipoff_time=ctx.tipoff_time,
            game_end=ctx.game_end,
            manifest=manifest,
            events=events,
            sport=gm.sport,
            fee_pct=fee_pct,
            settings=ctx.settings,
            entry_team=ctx.favorite_team,
            side="favorite",
            fee_model=scenario.fee_model if scenario.fee_model in ("taker", "maker") else "taker",
        )
        b_first = baseline_buy_first_ingame(
            trades_df=ctx.trades_df,
            tipoff_time=ctx.tipoff_time,
            game_end=ctx.game_end,
            manifest=manifest,
            events=events,
            sport=gm.sport,
            fee_pct=fee_pct,
            settings=ctx.settings,
            entry_team=ctx.favorite_team,
            side="favorite",
            fee_model=scenario.fee_model if scenario.fee_model in ("taker", "maker") else "taker",
        )
        baseline_open_roi = _baseline_roi(b_open)
        baseline_tip_roi = _baseline_roi(b_tip)
        baseline_first_roi = _baseline_roi(b_first)
    else:
        baseline_open_roi = float("nan")
        baseline_tip_roi = float("nan")
        baseline_first_roi = float("nan")

    row = {
        "scenario_name": scenario.name,
        "date": gm.date,
        "match_id": gm.match_id,
        "sport": gm.sport,
        "side": side,
        "entry_team": entry_team,
        "entry_token_id": pos.trigger.token_id,
        "entry_time": entry_time,
        "entry_price": entry_price,
        "exit_time": exit_time,
        "exit_price": float(pos.exit.exit_price),
        "exit_kind": pos.exit.exit_kind,
        "status": pos.exit.status,
        "position_index_in_game": pos.position_index_in_game,
        "settlement_payout": settlement.get("payout"),
        "pnl": pnl_dict.get("net_pnl_cents"),
        "roi_pct": pnl_dict.get("roi_pct"),
        "hold_seconds": pnl_dict.get("hold_seconds"),
        "max_drawdown_cents": _max_drawdown_cents(
            ctx.trades_df, entry_team, entry_time, exit_time, entry_price
        ),
        "baseline_buy_at_open_roi": baseline_open_roi,
        "baseline_buy_at_tipoff_roi": baseline_tip_roi,
        "baseline_buy_first_ingame_roi": baseline_first_roi,
    }
    for axis_name, axis_value in scenario.sweep_axes.items():
        row[f"sweep_axis_{axis_name}"] = axis_value
    return row


def _aggregate(per_position_df: pd.DataFrame, sweep_cols: List[str]) -> pd.DataFrame:
    if per_position_df.empty:
        return pd.DataFrame(
            columns=[
                "scenario_name",
                *sweep_cols,
                "count",
                "mean_roi_pct",
                "win_rate",
                "mean_hold_seconds",
                "mean_drawdown_cents",
                "forced_close_count",
            ]
        )
    group_cols = ["scenario_name"] + sweep_cols
    grouped = per_position_df.groupby(group_cols, dropna=False)

    def _agg(group: pd.DataFrame) -> pd.Series:
        net_pnl = pd.to_numeric(group["pnl"], errors="coerce")
        return pd.Series(
            {
                "count": int(len(group)),
                "mean_roi_pct": float(
                    pd.to_numeric(group["roi_pct"], errors="coerce").mean()
                ),
                "win_rate": float((net_pnl > 0).mean()) if len(group) else 0.0,
                "mean_hold_seconds": float(
                    pd.to_numeric(group["hold_seconds"], errors="coerce").mean()
                ),
                "mean_drawdown_cents": float(
                    pd.to_numeric(group["max_drawdown_cents"], errors="coerce").mean()
                ),
                "forced_close_count": int((group["status"] == "forced_close").sum()),
            }
        )

    return grouped.apply(_agg).reset_index()


def _universe_cache_key(scenario: Scenario) -> Tuple[str, str]:
    spec = scenario.universe_filter
    return (spec.name, json.dumps(dict(spec.params), sort_keys=True, default=str))


def run(
    scenarios: Iterable[Scenario],
    start_date: datetime,
    end_date: datetime,
    data_dir: str,
    settings: Optional[Mapping[str, Any]] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    *,
    context_builder: Optional[Callable[[GameMeta, Scenario, str, Mapping[str, Any]], Optional[Context]]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Run a list of scenarios, return (per_position_df, aggregation_df).

    Per-position rows include sweep axis columns (one per axis seen anywhere),
    settlement, baselines (NaN for non-favorite), and drawdown.
    Aggregation groups by scenario_name + sweep axes.
    """
    settings = dict(settings) if settings else {}
    builder = context_builder or _default_load_game_context

    scenarios = list(scenarios)
    rows: List[dict] = []
    sweep_axes_seen: set[str] = set()
    universes_cache: dict[Tuple[str, str], List[GameMeta]] = {}

    total = len(scenarios)
    for scen_idx, scenario in enumerate(scenarios):
        sweep_axes_seen.update(scenario.sweep_axes.keys())

        cache_key = _universe_cache_key(scenario)
        if cache_key not in universes_cache:
            ufilter = UNIVERSE_FILTERS[scenario.universe_filter.name]
            universes_cache[cache_key] = list(
                ufilter(start_date, end_date, scenario.universe_filter.params)
            )
        games = universes_cache[cache_key]

        for gm in games:
            ctx = builder(gm, scenario, data_dir, settings)
            if ctx is None:
                continue
            positions = run_scenario_on_game(scenario, ctx)
            for pos in positions:
                rows.append(_build_row(scenario, gm, ctx, pos, settings))

        if progress_callback is not None:
            progress_callback(scen_idx + 1, total, scenario.name)

    sweep_cols = [f"sweep_axis_{ax}" for ax in sorted(sweep_axes_seen)]
    columns = list(PER_POSITION_BASE_COLUMNS)
    insert_at = columns.index("scenario_name") + 1
    columns = columns[:insert_at] + sweep_cols + columns[insert_at:]

    for r in rows:
        for c in sweep_cols:
            r.setdefault(c, float("nan"))

    per_position_df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)

    if not per_position_df.empty:
        status_counts = per_position_df["status"].value_counts().to_dict()
        forced = int((per_position_df["status"] == "forced_close").sum())
        logger.info(
            "Runner status breakdown: %s (forced_close=%d, total positions=%d)",
            status_counts,
            forced,
            len(per_position_df),
        )

    aggregation_df = _aggregate(per_position_df, sweep_cols)
    return per_position_df, aggregation_df
