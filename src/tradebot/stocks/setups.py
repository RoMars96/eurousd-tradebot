"""Trade simulators for one stock on one day, on 1-minute bars.

Fill rules are deliberately harsh, because small-cap backtests flatter:
- slippage on every fill: max(slippage_min, slippage_pct% of price)
- a breakout fills at the breakout level, or the bar's open if it gapped
  past it -- never at a better price than was available
- a stop that's gapped through fills at the bar's open, not the stop
- if a bar touches both stop and target, the stop is assumed to fill first
- on the entry bar itself only the close is checked against the stop
  (the bar's low may have printed before the entry)

Results are in R: (exit - entry) / (entry - stop), all after slippage.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tradebot.stocks.pillars import OPEN, et_minutes


def _hhmm(value: str) -> int:
    h, m = (int(x) for x in value.split(":"))
    return h * 60 + m


@dataclass(frozen=True)
class TradeParams:
    entry_window_end: int = 10 * 60
    exit_time: int = 10 * 60 + 30
    target_r: float = 2.0
    stop_lookback_bars: int = 5
    min_stop_pct: float = 2.0
    surge_pct: float = 5.0
    pullback_bars: int = 2
    slippage_pct: float = 0.5
    slippage_min: float = 0.02

    @classmethod
    def from_config(cls, trade_cfg: dict) -> "TradeParams":
        return cls(
            entry_window_end=_hhmm(trade_cfg.get("entry_window_end_et", "10:00")),
            exit_time=_hhmm(trade_cfg.get("exit_time_et", "10:30")),
            target_r=trade_cfg.get("target_r", 2.0),
            stop_lookback_bars=trade_cfg.get("stop_lookback_bars", 5),
            min_stop_pct=trade_cfg.get("min_stop_pct", 2.0),
            surge_pct=trade_cfg.get("surge_pct", 5.0),
            pullback_bars=trade_cfg.get("pullback_bars", 2),
            slippage_pct=trade_cfg.get("slippage_pct", 0.5),
            slippage_min=trade_cfg.get("slippage_min", 0.02),
        )


@dataclass(frozen=True)
class SimTrade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry: float
    stop: float
    exit: float
    r: float
    ret_pct: float
    reason: str


class DayBars:
    """One symbol's minute bars for one day, as arrays."""

    def __init__(self, bars: pd.DataFrame) -> None:
        bars = bars.sort_values("time")
        self.times = pd.DatetimeIndex(bars["time"])
        self.minutes = et_minutes(bars["time"]).to_numpy()
        self.o = bars["open"].to_numpy(dtype=float)
        self.h = bars["high"].to_numpy(dtype=float)
        self.l = bars["low"].to_numpy(dtype=float)
        self.c = bars["close"].to_numpy(dtype=float)
        self.n = len(bars)
        after_open = np.flatnonzero(self.minutes >= OPEN)
        self.open_index = int(after_open[0]) if len(after_open) else None


def _slip(price: float, p: TradeParams) -> float:
    return max(p.slippage_min, price * p.slippage_pct / 100.0)


def _stop_for(day: DayBars, i: int, raw_entry: float, p: TradeParams) -> float:
    prior = day.l[max(0, i - p.stop_lookback_bars) : i]
    floor = raw_entry * (1.0 - p.min_stop_pct / 100.0)
    return min(float(prior.min()), floor) if len(prior) else floor


def _manage(day: DayBars, i: int, raw_entry: float, stop: float, p: TradeParams) -> SimTrade | None:
    if stop <= 0 or stop >= raw_entry:
        return None
    entry_fill = raw_entry + _slip(raw_entry, p)
    risk = entry_fill - stop
    target = raw_entry + p.target_r * (raw_entry - stop)

    j = i
    if day.c[i] <= stop:
        exit_raw, reason = day.c[i], "stop"
    else:
        exit_raw, reason = None, None
        for j in range(i + 1, day.n):
            if day.minutes[j] >= p.exit_time:
                exit_raw, reason = day.o[j], "time"
                break
            if day.l[j] <= stop:
                exit_raw, reason = min(stop, day.o[j]), "stop"
                break
            if day.h[j] >= target:
                exit_raw, reason = max(target, day.o[j]), "target"
                break
        if exit_raw is None:
            j = day.n - 1
            exit_raw, reason = day.c[j], "end_of_data"

    exit_fill = exit_raw - _slip(exit_raw, p)
    return SimTrade(
        entry_time=day.times[i],
        exit_time=day.times[j],
        entry=entry_fill,
        stop=stop,
        exit=exit_fill,
        r=(exit_fill - entry_fill) / risk,
        ret_pct=(exit_fill / entry_fill - 1.0) * 100.0,
        reason=reason,
    )


def _entry_range(day: DayBars, p: TradeParams) -> range:
    if day.open_index is None:
        return range(0)
    end = day.open_index
    while end < day.n and day.minutes[end] < p.entry_window_end:
        end += 1
    return range(day.open_index, end)


def gap_and_go(day: DayBars, premarket_high: float, p: TradeParams) -> SimTrade | None:
    """Buy the first break of the premarket high after the open."""
    if not np.isfinite(premarket_high):
        return None
    for i in _entry_range(day, p):
        if day.h[i] > premarket_high:
            raw_entry = min(max(premarket_high + 0.01, day.o[i]), day.h[i])
            return _manage(day, i, raw_entry, _stop_for(day, i, raw_entry, p), p)
    return None


def first_pullback(day: DayBars, p: TradeParams) -> SimTrade | None:
    """After a surge of surge_pct above the open, wait for pullback_bars
    lower-high bars, then buy the first bar that takes out the prior high.
    Stop under the pullback's low."""
    rng = _entry_range(day, p)
    if not rng:
        return None
    open0 = day.o[rng.start]
    surged = False
    pullback = 0
    pullback_low = np.inf
    for i in rng:
        if not surged:
            surged = day.h[i] >= open0 * (1.0 + p.surge_pct / 100.0)
            continue
        prev_high = day.h[i - 1]
        if pullback >= p.pullback_bars and day.h[i] > prev_high:
            raw_entry = min(max(prev_high + 0.01, day.o[i]), day.h[i])
            stop = min(pullback_low, raw_entry * (1.0 - p.min_stop_pct / 100.0))
            return _manage(day, i, raw_entry, stop, p)
        if day.h[i] < prev_high:
            pullback += 1
            pullback_low = min(pullback_low, day.l[i])
        else:
            pullback, pullback_low = 0, np.inf
    return None


def random_entry(day: DayBars, rng: np.random.Generator, p: TradeParams) -> SimTrade | None:
    """Benchmark: same stock, same window, same stop/exit rules, random entry minute."""
    window = _entry_range(day, p)
    if not window:
        return None
    i = int(rng.integers(window.start, window.stop))
    raw_entry = day.o[i]
    return _manage(day, i, raw_entry, _stop_for(day, i, raw_entry, p), p)
