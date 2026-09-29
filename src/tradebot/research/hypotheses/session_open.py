"""Hypothesis: price behaves predictably when London opens beyond the Asian range.

Each day, take the Asian-session (UTC) high/low. During the London window,
wait for price to pierce one side by `pierce_pips`. Then:

- "reversal": the first close back inside the range -> trade against the
  pierce (the liquidity-sweep folklore).
- "breakout": the first close beyond the level -> trade with the pierce.

Testing both, with the same machinery, lets the data say which (if
either) holds, instead of assuming the folklore is true. At most one event
per day; a bar that pierces both sides at once is ambiguous and skips the
day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradebot.strategy.sessions import compute_session_ranges


def london_open_events(
    df: pd.DataFrame,
    variant: str,
    pierce_pips: float,
    pip_size: float,
    asian_hours: tuple[int, int] = (0, 7),
    london_hours: tuple[int, int] = (7, 10),
) -> pd.Series:
    if variant not in ("reversal", "breakout"):
        raise ValueError(f"variant must be 'reversal' or 'breakout', got {variant!r}")

    ranges = {r.day: r for r in compute_session_ranges(df, "asian", *asian_hours)}
    hours = df.index.hour
    london = df.loc[(hours >= london_hours[0]) & (hours < london_hours[1])]
    pierce = pierce_pips * pip_size

    events: dict[pd.Timestamp, int] = {}
    for day, bars in london.groupby(london.index.normalize()):
        rng = ranges.get(day)
        if rng is None:
            continue
        highs = bars["high"].to_numpy()
        lows = bars["low"].to_numpy()
        closes = bars["close"].to_numpy()
        side = None
        for i in range(len(bars)):
            if side is None:
                up = highs[i] > rng.high + pierce
                down = lows[i] < rng.low - pierce
                if up and down:
                    break
                if up:
                    side = "high"
                elif down:
                    side = "low"
                else:
                    continue
            if variant == "breakout":
                if side == "high" and closes[i] > rng.high:
                    events[bars.index[i]] = 1
                    break
                if side == "low" and closes[i] < rng.low:
                    events[bars.index[i]] = -1
                    break
            else:
                if side == "high" and closes[i] < rng.high:
                    events[bars.index[i]] = -1
                    break
                if side == "low" and closes[i] > rng.low:
                    events[bars.index[i]] = 1
                    break

    return pd.Series(events, dtype="int64").sort_index()


def london_window_positions(df: pd.DataFrame, london_hours: tuple[int, int] = (7, 10)) -> np.ndarray:
    """Bar positions inside the London window -- the random-timing null draws from these."""
    hours = df.index.hour
    return np.flatnonzero((hours >= london_hours[0]) & (hours < london_hours[1]))
