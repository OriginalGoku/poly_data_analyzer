"""Shared application settings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChartSettings:
    """Runtime chart and analysis settings loaded from JSON."""

    open_anchor_stat: str = "vwap"
    open_anchor_window_min: int = 5
    analysis_min_open_favorite_price: float = 0.50
    vol_spike_std: float = 2.0
    vol_spike_lookback: int = 20
    pregame_min_cum_vol: float = 5000
    post_game_buffer_min: int = 10
    whale_min_volume_pct: float = 2.0
    whale_max_count: int = 10
    whale_maker_threshold_pct: float = 60.0
    whale_marker_min_trade_pct: float = 0.25
    sensitivity_price_window_trades: int = 5
    sensitivity_lead_bin_close: int = 5
    sensitivity_lead_bin_moderate: int = 12
    discrepancy_dead_zone_low: float = 0.49
    discrepancy_dead_zone_high: float = 0.51
    discrepancy_min_trades: int = 5
    discrepancy_max_trade_gap_seconds: int = 120
    discrepancy_forward_return_horizon_minutes: int = 12
    regime_forward_horizon_minutes: int = 12
    regime_min_trades_in_window: int = 3
    regime_max_trade_gap_seconds: int = 120
    dip_thresholds: tuple[float, ...] = (0.05, 0.04, 0.03, 0.02)
    dip_min_trades: int = 3
    dip_max_trade_gap_seconds: int = 120
    dip_recovery_horizon_minutes: int = 15

    @classmethod
    def from_dict(cls, data: dict) -> "ChartSettings":
        if "dip_thresholds" in data:
            data = dict(data)
            data["dip_thresholds"] = tuple(data["dip_thresholds"])
        return cls(**data)

    def to_dict(self) -> dict:
        return {
            "open_anchor_stat": self.open_anchor_stat,
            "open_anchor_window_min": self.open_anchor_window_min,
            "analysis_min_open_favorite_price": self.analysis_min_open_favorite_price,
            "vol_spike_std": self.vol_spike_std,
            "vol_spike_lookback": self.vol_spike_lookback,
            "pregame_min_cum_vol": self.pregame_min_cum_vol,
            "post_game_buffer_min": self.post_game_buffer_min,
            "whale_min_volume_pct": self.whale_min_volume_pct,
            "whale_max_count": self.whale_max_count,
            "whale_maker_threshold_pct": self.whale_maker_threshold_pct,
            "whale_marker_min_trade_pct": self.whale_marker_min_trade_pct,
            "sensitivity_price_window_trades": self.sensitivity_price_window_trades,
            "sensitivity_lead_bin_close": self.sensitivity_lead_bin_close,
            "sensitivity_lead_bin_moderate": self.sensitivity_lead_bin_moderate,
            "discrepancy_dead_zone_low": self.discrepancy_dead_zone_low,
            "discrepancy_dead_zone_high": self.discrepancy_dead_zone_high,
            "discrepancy_min_trades": self.discrepancy_min_trades,
            "discrepancy_max_trade_gap_seconds": self.discrepancy_max_trade_gap_seconds,
            "discrepancy_forward_return_horizon_minutes": self.discrepancy_forward_return_horizon_minutes,
            "regime_forward_horizon_minutes": self.regime_forward_horizon_minutes,
            "regime_min_trades_in_window": self.regime_min_trades_in_window,
            "regime_max_trade_gap_seconds": self.regime_max_trade_gap_seconds,
            "dip_thresholds": list(self.dip_thresholds),
            "dip_min_trades": self.dip_min_trades,
            "dip_max_trade_gap_seconds": self.dip_max_trade_gap_seconds,
            "dip_recovery_horizon_minutes": self.dip_recovery_horizon_minutes,
        }


def load_chart_settings(settings_path: str | Path) -> ChartSettings:
    path = Path(settings_path)
    with open(path, encoding="utf-8") as f:
        return ChartSettings.from_dict(json.load(f))
