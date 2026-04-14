"""Backtest configuration and sport-specific parameters."""
from dataclasses import dataclass
from typing import Literal, Tuple


@dataclass(frozen=True)
class DipBuyBacktestConfig:
    """Configuration for dip-buy backtest strategy.

    Attributes:
        dip_thresholds: Tuple of dip amounts in cents (e.g., (10, 15, 20))
        exit_type: Exit strategy - "settlement", "reversion_to_open",
                  "reversion_to_partial", or "fixed_profit"
        profit_target: For fixed_profit exit, target in cents
        fee_model: "taker" (0.2% Polymarket fee) or "maker" (0% fee)
        sport_filter: "nba", "nhl", "mlb", or "all"
    """
    dip_thresholds: Tuple[int, ...] = (10, 15, 20)
    dip_anchor: Literal["open", "tipoff"] = "open"
    exit_type: Literal["settlement", "reversion_to_open", "reversion_to_partial",
                       "fixed_profit"] = "settlement"
    profit_target: int = 5  # cents, for reversion_to_partial and fixed_profit
    fee_model: Literal["taker", "maker"] = "taker"
    sport_filter: Literal["nba", "nhl", "mlb", "all"] = "nba"

    # Fee schedule (Polymarket Q1 2026)
    taker_fee_pct: float = 0.002  # 0.2%
    maker_fee_pct: float = 0.0

    @property
    def fee_pct(self) -> float:
        """Return fee % based on fee_model."""
        return self.taker_fee_pct if self.fee_model == "taker" else self.maker_fee_pct

    def __post_init__(self):
        """Validate configuration."""
        if not self.dip_thresholds:
            raise ValueError("dip_thresholds must be non-empty")
        if self.profit_target < 0:
            raise ValueError("profit_target must be >= 0")
