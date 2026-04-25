"""PositionManager — owns open positions for one game and admits new triggers.

Two lock modes:

- ``sequential``: at most one open position; cool-down + optional permanent
  block after a stop-loss exit.
- ``scale_in``: up to ``max_entries`` concurrent positions; min-spacing via
  cool-down between consecutive entries; ``allow_re_arm_after_stop_loss`` is
  ignored (warned at construction).
"""
from __future__ import annotations

import dataclasses
import warnings
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import pandas as pd

from backtest.contracts import Context, Exit, LockSpec, Position


ExitScanner = Callable[[Context, pd.Timestamp], Optional[Exit]]


@dataclass
class _Slot:
    position: Position
    exit_scanner: ExitScanner
    closed: bool = False


class PositionManager:
    def __init__(self, lock: LockSpec) -> None:
        if lock.mode not in ("sequential", "scale_in"):
            raise ValueError(f"Unsupported lock mode: {lock.mode!r}")
        if lock.mode == "scale_in" and lock.allow_re_arm_after_stop_loss:
            warnings.warn(
                "allow_re_arm_after_stop_loss is ignored in scale_in mode",
                stacklevel=2,
            )
        self._lock = lock
        self._slots: List[_Slot] = []
        self._last_entry_time: Optional[pd.Timestamp] = None
        self._last_exit_time: Optional[pd.Timestamp] = None
        self._last_exit_kind: Optional[str] = None
        self._stop_loss_blocked: bool = False
        self._last_ctx: Optional[Context] = None

    # ---- introspection ----
    def total_entries(self) -> int:
        return len(self._slots)

    def open_count(self) -> int:
        return sum(1 for s in self._slots if not s.closed)

    def closed_positions(self) -> List[Position]:
        return [s.position for s in self._slots if s.closed]

    def positions(self) -> List[Position]:
        """All slots' current Position objects (may have placeholder exit if open)."""
        return [s.position for s in self._slots]

    # ---- core API ----
    def can_open(self, now: pd.Timestamp) -> bool:
        cooldown = pd.Timedelta(seconds=self._lock.cool_down_seconds)
        if self._lock.mode == "sequential":
            if self.open_count() > 0:
                return False
            if self._stop_loss_blocked:
                return False
            if self._last_exit_time is not None and now < self._last_exit_time + cooldown:
                return False
            return True
        # scale_in
        if self.total_entries() >= self._lock.max_entries:
            return False
        if self._last_entry_time is not None and now < self._last_entry_time + cooldown:
            return False
        return True

    def register_position(self, pos: Position, exit_scanner: ExitScanner) -> None:
        if not self.can_open(pos.trigger.trigger_time):
            raise RuntimeError(
                "register_position called while can_open is False; "
                "engine must check can_open first"
            )
        self._slots.append(_Slot(position=pos, exit_scanner=exit_scanner))
        self._last_entry_time = pos.trigger.trigger_time

    def tick(self, ctx: Context, now: pd.Timestamp) -> None:
        self._last_ctx = ctx
        for slot in self._slots:
            if slot.closed:
                continue
            exit_obj = slot.exit_scanner(ctx, now)
            if exit_obj is None:
                continue
            if exit_obj.exit_time is None:
                raise ValueError("Exit.exit_time must be non-None")
            self._close_slot(slot, exit_obj)

    def next_eligible_time(
        self, now: pd.Timestamp, game_end: pd.Timestamp
    ) -> pd.Timestamp:
        if self.can_open(now):
            return now
        if self.exhausted():
            return game_end
        cooldown = pd.Timedelta(seconds=self._lock.cool_down_seconds)
        if self._lock.mode == "sequential":
            if self._stop_loss_blocked:
                return game_end
            if self.open_count() > 0:
                # Cannot predict when scanner-driven exit will fire.
                return game_end
            if self._last_exit_time is not None:
                candidate = self._last_exit_time + cooldown
                return min(candidate, game_end) if candidate > now else now
            return now
        # scale_in
        if self.total_entries() >= self._lock.max_entries:
            return game_end
        if self._last_entry_time is not None:
            candidate = self._last_entry_time + cooldown
            return min(candidate, game_end) if candidate > now else now
        return now

    def force_close_all(self, at: pd.Timestamp) -> None:
        ctx = self._last_ctx
        for slot in self._slots:
            if slot.closed:
                continue
            team = slot.position.trigger.team
            price = self._last_price_for_team(ctx, team, at)
            if price is None:
                price = float(slot.position.trigger.trigger_price)
            forced = Exit(
                exit_time=at,
                exit_price=float(price),
                exit_kind="forced_close",
                status="forced_close",
            )
            self._close_slot(slot, forced)

    def exhausted(self) -> bool:
        if self.open_count() > 0:
            return False
        if self._lock.mode == "sequential":
            return self._stop_loss_blocked
        return self.total_entries() >= self._lock.max_entries

    # ---- internals ----
    def _close_slot(self, slot: _Slot, exit_obj: Exit) -> None:
        slot.position = dataclasses.replace(slot.position, exit=exit_obj)
        slot.closed = True
        self._last_exit_time = exit_obj.exit_time
        self._last_exit_kind = exit_obj.exit_kind
        if (
            self._lock.mode == "sequential"
            and exit_obj.exit_kind == "stop_loss"
            and not self._lock.allow_re_arm_after_stop_loss
        ):
            self._stop_loss_blocked = True

    @staticmethod
    def _last_price_for_team(
        ctx: Optional[Context], team: str, at: pd.Timestamp
    ) -> Optional[float]:
        if ctx is None:
            return None
        df = ctx.trades_df
        if df is None or df.empty:
            return None
        time_col = "datetime" if "datetime" in df.columns else None
        if time_col is None:
            return None
        sub = df[df[time_col] <= at]
        if "team" in sub.columns:
            sub = sub[sub["team"] == team]
        if sub.empty:
            return None
        if "price" not in sub.columns:
            return None
        return float(sub["price"].iloc[-1])
