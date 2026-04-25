"""Baseline strategy implementations for backtest comparison."""
from typing import Dict, Optional

import pandas as pd

from backtest.backtest_pnl import compute_trade_pnl
from backtest.backtest_settlement import resolve_settlement


_SENTINEL = object()


def _resolve_entry_team(entry_team, open_favorite_team):
    if entry_team is not _SENTINEL and open_favorite_team is not _SENTINEL:
        raise TypeError(
            "pass either entry_team or open_favorite_team, not both"
        )
    if entry_team is not _SENTINEL:
        return entry_team
    if open_favorite_team is not _SENTINEL:
        return open_favorite_team
    return None


def _resolve_token_id(manifest: Dict, entry_team: Optional[str]) -> Optional[str]:
    token_ids = manifest.get("token_ids") or []
    if entry_team is None:
        return None
    if entry_team == manifest.get("away_team") and len(token_ids) >= 1:
        return token_ids[0]
    if entry_team == manifest.get("home_team") and len(token_ids) >= 2:
        return token_ids[1]
    return None


def _skipped_non_favorite_result(side: str) -> Dict:
    nan = float("nan")
    return {
        "entry_price": nan,
        "exit_price": nan,
        "team": None,
        "token_id": None,
        "side": side,
        "gross_pnl_cents": nan,
        "net_pnl_cents": nan,
        "roi_pct": nan,
        "hold_seconds": nan,
        "fee_cost_cents": nan,
        "settlement_method": None,
        "settlement_occurred": False,
        "true_pnl_cents": nan,
        "status": "skipped_non_favorite",
    }


def _empty_result(entry_price, team, token_id, side):
    return {
        "entry_price": entry_price,
        "exit_price": None,
        "team": team,
        "token_id": token_id,
        "side": side,
        "gross_pnl_cents": 0,
        "net_pnl_cents": 0,
        "roi_pct": 0,
        "hold_seconds": 0,
        "fee_cost_cents": 0,
        "settlement_method": None,
        "settlement_occurred": False,
        "true_pnl_cents": None,
    }


def baseline_buy_at_open(
    open_price: float,
    trades_df: pd.DataFrame,
    tipoff_time,
    game_end,
    manifest: Dict,
    events,
    sport: str,
    fee_pct: float,
    settings,
    entry_team=_SENTINEL,
    open_favorite_team=_SENTINEL,
    side: str = "favorite",
    fee_model: str = "taker",
) -> Dict:
    """Baseline: buy at open, hold to settlement."""
    if side != "favorite":
        return _skipped_non_favorite_result(side)

    team = _resolve_entry_team(entry_team, open_favorite_team)
    token_id = _resolve_token_id(manifest, team)

    if trades_df.empty:
        return _empty_result(open_price, team, token_id, side)

    in_game = trades_df[
        (trades_df["datetime"] >= tipoff_time) & (trades_df["datetime"] < game_end)
    ]
    exit_trade = None if in_game.empty else in_game.iloc[-1]

    entry = {
        "entry_price": open_price,
        "entry_time": None,
        "team": team,
        "token_id": token_id,
        "side": side,
    }

    if exit_trade is not None:
        exit_ = {
            "exit_price": exit_trade["price"],
            "exit_time": exit_trade["datetime"],
            "hold_seconds": int((exit_trade["datetime"] - tipoff_time).total_seconds()),
        }
    else:
        exit_ = {"exit_price": None, "exit_time": None, "hold_seconds": 0}

    settlement = resolve_settlement(
        manifest, events, trades_df, game_end, sport, settings,
        entry_team=team,
    )

    return compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model=fee_model,
        fee_pct=fee_pct,
        settings=settings,
    )


def baseline_buy_at_tipoff(
    tipoff_price: float,
    trades_df: pd.DataFrame,
    tipoff_time,
    game_end,
    manifest: Dict,
    events,
    sport: str,
    fee_pct: float,
    settings,
    entry_team=_SENTINEL,
    open_favorite_team=_SENTINEL,
    side: str = "favorite",
    fee_model: str = "taker",
) -> Dict:
    """Baseline: buy at tipoff, hold to settlement."""
    if side != "favorite":
        return _skipped_non_favorite_result(side)

    team = _resolve_entry_team(entry_team, open_favorite_team)
    token_id = _resolve_token_id(manifest, team)

    if trades_df.empty:
        return _empty_result(tipoff_price, team, token_id, side)

    in_game = trades_df[
        (trades_df["datetime"] >= tipoff_time) & (trades_df["datetime"] < game_end)
    ]
    exit_trade = None if in_game.empty else in_game.iloc[-1]

    entry = {
        "entry_price": tipoff_price,
        "entry_time": tipoff_time,
        "team": team,
        "token_id": token_id,
        "side": side,
    }

    if exit_trade is not None:
        exit_ = {
            "exit_price": exit_trade["price"],
            "exit_time": exit_trade["datetime"],
            "hold_seconds": int((exit_trade["datetime"] - tipoff_time).total_seconds()),
        }
    else:
        exit_ = {"exit_price": None, "exit_time": None, "hold_seconds": 0}

    settlement = resolve_settlement(
        manifest, events, trades_df, game_end, sport, settings,
        entry_team=team,
    )

    return compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model=fee_model,
        fee_pct=fee_pct,
        settings=settings,
    )


def baseline_buy_first_ingame(
    trades_df: pd.DataFrame,
    tipoff_time,
    game_end,
    manifest: Dict,
    events,
    sport: str,
    fee_pct: float,
    settings,
    entry_team=_SENTINEL,
    open_favorite_team=_SENTINEL,
    side: str = "favorite",
    fee_model: str = "taker",
) -> Dict:
    """Baseline: buy at first in-game trade, hold to settlement."""
    if side != "favorite":
        return _skipped_non_favorite_result(side)

    team = _resolve_entry_team(entry_team, open_favorite_team)
    token_id = _resolve_token_id(manifest, team)

    if trades_df.empty:
        return _empty_result(None, team, token_id, side)

    in_game = trades_df[
        (trades_df["datetime"] >= tipoff_time) & (trades_df["datetime"] < game_end)
    ]

    if in_game.empty:
        return _empty_result(None, team, token_id, side)

    entry_trade = in_game.iloc[0]
    exit_trade = in_game.iloc[-1]

    entry = {
        "entry_price": entry_trade["price"],
        "entry_time": entry_trade["datetime"],
        "team": team,
        "token_id": token_id,
        "side": side,
    }

    exit_ = {
        "exit_price": exit_trade["price"],
        "exit_time": exit_trade["datetime"],
        "hold_seconds": int((exit_trade["datetime"] - entry_trade["datetime"]).total_seconds()),
    }

    settlement = resolve_settlement(
        manifest, events, trades_df, game_end, sport, settings,
        entry_team=team,
    )

    return compute_trade_pnl(
        entry=entry,
        exit_=exit_,
        settlement=settlement,
        fee_model=fee_model,
        fee_pct=fee_pct,
        settings=settings,
    )
