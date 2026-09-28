"""Session-window range detection (e.g. the Asian session high/low)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SessionRange:
    session: str
    day: pd.Timestamp
    start: pd.Timestamp
    end: pd.Timestamp
    high: float
    low: float


def compute_session_ranges(
    df: pd.DataFrame, session_name: str, start_hour: int, end_hour: int
) -> list[SessionRange]:
    """Compute one high/low range per calendar day for an hour-of-day window (UTC).

    `start_hour`/`end_hour` are in [0, 24); a window that does not wrap
    midnight is assumed (end_hour > start_hour).
    """
    if not 0 <= start_hour < end_hour <= 24:
        raise ValueError("session window must satisfy 0 <= start_hour < end_hour <= 24")

    hours = df.index.hour
    mask = (hours >= start_hour) & (hours < end_hour)
    windowed = df.loc[mask]
    if windowed.empty:
        return []

    ranges: list[SessionRange] = []
    for day, group in windowed.groupby(windowed.index.normalize()):
        ranges.append(
            SessionRange(
                session=session_name,
                day=day,
                start=group.index[0],
                end=group.index[-1],
                high=float(group["high"].max()),
                low=float(group["low"].min()),
            )
        )
    return ranges


def active_session_range(
    ranges: list[SessionRange], at_time: pd.Timestamp
) -> SessionRange | None:
    """Return the most recently completed session range as of `at_time`."""
    candidates = [r for r in ranges if r.end < at_time]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.end)
