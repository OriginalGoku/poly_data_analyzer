"""PnL computation for backtest trades."""
from typing import Dict, Optional

import pandas as pd


def compute_trade_pnl(
    entry: Dict,
    exit_: Dict,
    settlement: Optional[tuple],
    fee_model: str,
    fee_pct: float,
    settings,
) -> Dict:
    """Compute PnL metrics for a trade.

    Args:
        entry: Dict with entry_price, entry_time, team, token_id, side
        exit_: Dict with exit_price, exit_time, hold_seconds
        settlement: Tuple of (payout, method, settled) from resolve_settlement;
                   or None
        fee_model: "taker" or "maker"
        fee_pct: Fee percentage (e.g., 0.002 for 0.2%)
        settings: ChartSettings instance

    Returns:
        Dict with PnL metrics:
        - entry_price, exit_price
        - team, token_id, side (propagated from entry)
        - gross_pnl_cents, net_pnl_cents
        - roi_pct, hold_seconds
        - settlement_method, settlement_occurred
        - true_pnl_cents (only if settled)
    """
    entry_price = entry.get("entry_price")
    team = entry["team"]
    token_id = entry["token_id"]
    side = entry["side"]
    exit_price = exit_.get("exit_price")
    hold_seconds = exit_.get("hold_seconds", 0)

    # Compute gross and net PnL (in cents)
    if exit_price is not None:
        gross_pnl_cents = (exit_price - entry_price) * 100
        fee_cost = (entry_price + exit_price) * fee_pct * 100
        net_pnl_cents = gross_pnl_cents - fee_cost
        roi_pct = (net_pnl_cents / (entry_price * 100)) if entry_price > 0 else 0
    else:
        gross_pnl_cents = 0
        fee_cost = 0
        net_pnl_cents = 0
        roi_pct = 0

    # Settlement and true PnL
    settlement_method = None
    settlement_occurred = False
    true_pnl_cents = None

    if settlement is not None:
        payout, method, settled = settlement
        settlement_method = method
        settlement_occurred = settled

        if settled and payout is not None:
            true_pnl_cents = (payout - entry_price) * 100

    return {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "team": team,
        "token_id": token_id,
        "side": side,
        "gross_pnl_cents": gross_pnl_cents,
        "net_pnl_cents": net_pnl_cents,
        "roi_pct": roi_pct,
        "hold_seconds": hold_seconds,
        "fee_cost_cents": fee_cost,
        "settlement_method": settlement_method,
        "settlement_occurred": settlement_occurred,
        "true_pnl_cents": true_pnl_cents,
    }
