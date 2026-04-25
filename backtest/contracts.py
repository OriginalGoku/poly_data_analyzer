"""Core data contracts for the backtest engine redesign.

Frozen dataclasses describing the immutable inputs/outputs flowing between
universe filters, triggers, exits, the position manager, and the engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ComponentSpec:
    """Reference to a registered component (universe filter / trigger / exit)."""
    name: str
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LockSpec:
    """Per-scenario locking / re-entry policy."""
    mode: str  # "sequential" | "scale_in"
    max_entries: int = 1
    cool_down_seconds: float = 0.0
    allow_re_arm_after_stop_loss: bool = False


@dataclass(frozen=True)
class Scenario:
    """A fully concrete backtest scenario (no sweep markers)."""
    name: str
    universe_filter: ComponentSpec
    side_target: str  # "favorite" | "underdog"
    trigger: ComponentSpec
    exit: ComponentSpec
    lock: LockSpec
    fee_model: str
    sweep_axes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GameMeta:
    """Per-game metadata produced by the universe filter."""
    date: str
    match_id: str
    sport: str
    open_fav_price: float
    tipoff_fav_price: float
    open_fav_token_id: str
    can_settle: bool
    price_quality: str
    open_favorite_team: str


@dataclass(frozen=True)
class Trigger:
    """Output of a trigger scanner — describes a candidate entry."""
    trigger_time: pd.Timestamp
    trigger_price: float
    team: str
    token_id: str
    side: str  # "yes" | "no"
    anchor_price: Optional[float] = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Exit:
    """Output of an exit scanner — exit_time is required (non-None)."""
    exit_time: pd.Timestamp
    exit_price: float
    exit_kind: str
    status: str


@dataclass(frozen=True)
class Position:
    """A trigger paired with its resolved exit."""
    trigger: Trigger
    exit: Exit
    position_index_in_game: int
    settlement: Optional[Mapping[str, Any]] = None


@dataclass(frozen=True)
class Context:
    """Per-game immutable context handed to triggers and exits."""
    trades_df: pd.DataFrame
    trades_time_array: np.ndarray
    favorite_team: str
    underdog_team: str
    open_prices: Mapping[str, float]
    tipoff_prices: Mapping[str, float]
    tipoff_time: Optional[pd.Timestamp]
    game_end: Optional[pd.Timestamp]
    game_meta: GameMeta
    scenario: Scenario
    settings: Mapping[str, Any] = field(default_factory=dict)

    def slice_after(
        self, after_time: datetime, team: Optional[str] = None
    ) -> pd.DataFrame:
        """Return rows with timestamp strictly greater than `after_time`.

        Uses np.searchsorted on the pre-built sorted time array. Returns a view
        (no copy); callers must treat as read-only.
        """
        arr = self.trades_time_array
        key = np.datetime64(pd.Timestamp(after_time))
        idx = np.searchsorted(arr, key, side="right")
        sliced = self.trades_df.iloc[idx:]
        if team is not None and "team" in sliced.columns:
            sliced = sliced[sliced["team"] == team]
        return sliced
