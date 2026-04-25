"""Per-game engine loop.

Runs one Scenario on one game Context, returning a list of Position objects
with settlement + PnL populated.
"""
from __future__ import annotations

import dataclasses
from typing import Any, List, Mapping, Optional

import pandas as pd

from backtest.backtest_pnl import compute_trade_pnl
from backtest.backtest_settlement import resolve_settlement
from backtest.contracts import Context, Exit, Position, Scenario
from backtest.position_manager import PositionManager
from backtest.registry import EXITS, TRIGGERS


_DEFAULT_FEES: Mapping[str, float] = {"taker": 0.002, "maker": 0.0}


def fee_pct_for(fee_model: str, settings: Optional[Mapping[str, Any]] = None) -> float:
    """Resolve fee percentage for a fee model, with optional settings override."""
    if settings is not None:
        key = f"fee_{fee_model}_pct"
        if key in settings:
            return float(settings[key])
        fees = settings.get("fees")
        if isinstance(fees, Mapping) and fee_model in fees:
            return float(fees[fee_model])
    if fee_model not in _DEFAULT_FEES:
        raise ValueError(f"Unknown fee_model: {fee_model!r}")
    return _DEFAULT_FEES[fee_model]


def _placeholder_exit(at: pd.Timestamp) -> Exit:
    return Exit(exit_time=at, exit_price=0.0, exit_kind="open", status="open")


def run_scenario_on_game(scenario: Scenario, ctx: Context) -> List[Position]:
    """Run one scenario on one game. Returns positions with settlement+pnl populated."""
    pm = PositionManager(scenario.lock)
    trigger_fn = TRIGGERS[scenario.trigger.name]
    exit_factory = EXITS[scenario.exit.name]

    if ctx.tipoff_time is None or ctx.game_end is None:
        return []

    cursor: pd.Timestamp = ctx.tipoff_time
    game_end: pd.Timestamp = ctx.game_end
    next_index = 0

    while cursor < game_end and not pm.exhausted():
        pm.tick(ctx, cursor)
        if not pm.can_open(cursor):
            nxt = pm.next_eligible_time(cursor, game_end)
            if nxt <= cursor:
                # Defensive: avoid infinite loop if pm reports same time.
                cursor = cursor + pd.Timedelta(microseconds=1)
            else:
                cursor = nxt
            continue
        trigger = trigger_fn(ctx, cursor, scenario.trigger.params)
        if trigger is None:
            break
        pos = Position(
            trigger=trigger,
            exit=_placeholder_exit(trigger.trigger_time),
            position_index_in_game=next_index,
        )
        pm.register_position(pos, exit_scanner=exit_factory(ctx, trigger, scenario.exit.params))
        next_index += 1
        cursor = trigger.trigger_time + pd.Timedelta(microseconds=1)

    pm.force_close_all(game_end)

    positions = pm.positions()
    finalized: List[Position] = []
    fee_pct = fee_pct_for(scenario.fee_model, ctx.settings)
    manifest = ctx.settings.get("manifest") if isinstance(ctx.settings, Mapping) else None
    events = ctx.settings.get("events") if isinstance(ctx.settings, Mapping) else None

    for pos in positions:
        settlement = resolve_settlement(
            manifest if manifest is not None else {},
            events,
            ctx.trades_df,
            game_end,
            ctx.game_meta.sport,
            ctx.settings,
            entry_team=pos.trigger.team,
        )
        hold_seconds = int(
            (pos.exit.exit_time - pos.trigger.trigger_time).total_seconds()
        )
        entry = {
            "entry_time": pos.trigger.trigger_time,
            "entry_price": pos.trigger.trigger_price,
            "team": pos.trigger.team,
            "token_id": pos.trigger.token_id,
            "side": pos.trigger.side,
        }
        exit_dict = {
            "exit_time": pos.exit.exit_time,
            "exit_price": pos.exit.exit_price,
            "exit_type": pos.exit.exit_kind,
            "status": pos.exit.status,
            "hold_seconds": hold_seconds,
        }
        pnl = compute_trade_pnl(
            entry=entry,
            exit_=exit_dict,
            settlement=settlement,
            fee_model=scenario.fee_model,
            fee_pct=fee_pct,
            settings=ctx.settings,
        )
        payout, method, settled = settlement
        settlement_map = {
            "payout": payout,
            "method": method,
            "settled": settled,
            "pnl": pnl,
        }
        finalized.append(dataclasses.replace(pos, settlement=settlement_map))

    return finalized
