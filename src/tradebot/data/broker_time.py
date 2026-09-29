"""Correct MT5's broker-server-time candle timestamps to true UTC.

MT5's Python API returns candle timestamps in the broker's own server
time, NOT UTC -- even though it's convenient to just slap a UTC label on
them. Most brokers (IC Markets included) run their MT5 servers on
GMT+2/GMT+3, shifting with EU daylight saving, which is a *different*
transition schedule than the pair's own trading hours. If left
uncorrected, every session-window calculation in this bot (Asian/London/NY
hour ranges) would silently sample the wrong candles.

This has NOT been verified against a live MT5 connection (this repo was
built in a network-sandboxed environment) -- see
scripts/check_broker_time_offset.py, which you should run once you have
MT5 running, to confirm the configured offset actually matches your
broker's clock before trusting any session-based signal on live data.

The DST boundary used here (last Sunday of March / October, 01:00 UTC) is
the standard EU convention that most MT5 brokers follow for their server
clock. It's a same-quarter approximation, not minute-exact: right at the
few-hour window of the actual transition, a handful of candles could be
mislabeled by one hour. That's a minor, twice-a-year edge case, not a
reason to distrust the correction the rest of the year.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd


def _last_sunday(year: int, month: int) -> dt.date:
    if month == 12:
        next_month_first = dt.date(year + 1, 1, 1)
    else:
        next_month_first = dt.date(year, month + 1, 1)
    last_day = next_month_first - dt.timedelta(days=1)
    days_since_sunday = (last_day.weekday() - 6) % 7  # Monday=0 ... Sunday=6
    return last_day - dt.timedelta(days=days_since_sunday)


def broker_utc_offset_hours(
    moment: dt.datetime,
    standard_offset_hours: int,
    dst_offset_hours: int,
    dst_rule: str = "eu",
) -> int:
    """Hours to SUBTRACT from a broker-time timestamp to get true UTC."""
    if dst_rule == "none":
        return standard_offset_hours
    if dst_rule != "eu":
        raise ValueError(f"Unsupported dst_rule {dst_rule!r}, expected 'eu' or 'none'")

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)

    year = moment.year
    dst_start = dt.datetime.combine(_last_sunday(year, 3), dt.time(1, 0), tzinfo=dt.timezone.utc)
    dst_end = dt.datetime.combine(_last_sunday(year, 10), dt.time(1, 0), tzinfo=dt.timezone.utc)

    if dst_start <= moment < dst_end:
        return dst_offset_hours
    return standard_offset_hours


def correct_broker_index_to_utc(
    index: pd.DatetimeIndex,
    standard_offset_hours: int,
    dst_offset_hours: int,
    dst_rule: str = "eu",
) -> pd.DatetimeIndex:
    """Shift a DatetimeIndex that's mislabeled as UTC but is really broker time."""
    if standard_offset_hours == 0 and dst_offset_hours == 0:
        return index  # no-op fast path, e.g. dst_rule == "none" with a 0 offset

    offsets_hours = [
        broker_utc_offset_hours(t.to_pydatetime(), standard_offset_hours, dst_offset_hours, dst_rule)
        for t in index
    ]
    return index - pd.to_timedelta(offsets_hours, unit="h")
