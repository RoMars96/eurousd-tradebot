"""Account-level risk guardrails: daily loss limit and concurrency cap."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class RiskGuard:
    daily_loss_limit_pct: float
    max_concurrent_positions: int
    _day: pd.Timestamp | None = field(default=None, init=False, repr=False)
    _day_start_equity: float = field(default=0.0, init=False, repr=False)
    _halted_today: bool = field(default=False, init=False, repr=False)

    def roll_day(self, current_time: pd.Timestamp, equity: float) -> None:
        day = current_time.normalize()
        if self._day is None or day != self._day:
            self._day = day
            self._day_start_equity = equity
            self._halted_today = False

    def register_equity(self, current_time: pd.Timestamp, equity: float) -> None:
        self.roll_day(current_time, equity)
        if self._day_start_equity <= 0:
            return
        drawdown_pct = (self._day_start_equity - equity) / self._day_start_equity * 100.0
        if drawdown_pct >= self.daily_loss_limit_pct:
            self._halted_today = True

    def can_open_position(self, open_position_count: int) -> bool:
        if self._halted_today:
            return False
        return open_position_count < self.max_concurrent_positions

    @property
    def halted_today(self) -> bool:
        return self._halted_today
