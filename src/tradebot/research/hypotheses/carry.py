"""Hypothesis: the UK-Japan interest-rate differential predicts GBP/JPY.

Monthly decisions, held for one month. Two variants:

- "level": long when the UK rate exceeds the JP rate by more than
  `min_diff` (pure carry), short when JP exceeds UK by that much, flat
  otherwise.
- "momentum": trade in the direction the differential moved over the last
  `lookback` months (widening -> long GBP/JPY, narrowing -> short).

Each trade earns the price move plus overnight carry: long GBP/JPY is paid
roughly (UK - JP rate) on the position, short pays it. Brokers pass on
only part of positive carry (`swap_efficiency`) and charge negative carry
in full; check your account's actual GBPJPY swap rates in MT5.

Rates for month t are lagged by `publication_lag_months` before use, since
monthly-average series aren't known until after the month ends.

Rates CSV format: columns `date`, `uk`, `jp` in percent (e.g. 5.25). Any
frequency; it's resampled to month-end, forward-filling step-changes like
central-bank policy rates.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def load_rates_csv(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in ("date", "uk", "jp") if c not in df.columns]
    if missing:
        raise ValueError(f"rates CSV {path} is missing column(s) {missing}; need date, uk, jp")
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("date").sort_index()[["uk", "jp"]].astype(float)
    return df.resample("ME").last().ffill()


def month_end_close(ohlc: pd.DataFrame) -> pd.Series:
    return ohlc["close"].resample("ME").last().dropna()


def rate_differential(rates: pd.DataFrame, lag_months: int) -> pd.Series:
    return (rates["uk"] - rates["jp"]).shift(lag_months).dropna()


def level_events(diff: pd.Series, min_diff: float) -> pd.Series:
    direction = np.where(diff > min_diff, 1, np.where(diff < -min_diff, -1, 0))
    events = pd.Series(direction, index=diff.index, dtype="int64")
    return events[events != 0]


def momentum_events(diff: pd.Series, lookback: int) -> pd.Series:
    change = diff - diff.shift(lookback)
    events = np.sign(change).dropna().astype("int64")
    return events[events != 0]


def carry_trades(
    close_me: pd.Series,
    diff: pd.Series,
    events: pd.Series,
    pip_size: float,
    cost_pips: float,
    swap_efficiency: float,
) -> pd.DataFrame:
    """Enter at month-end t, exit at month-end t+1, earning price move + carry."""
    events = events[events.index.isin(close_me.index) & events.index.isin(diff.index)]
    positions = close_me.index.get_indexer(events.index)
    valid = positions + 1 < len(close_me)
    positions = positions[valid]
    events = events[valid]

    entry = close_me.to_numpy()[positions]
    exit_ = close_me.to_numpy()[positions + 1]
    direction = events.to_numpy(dtype=float)
    price_pips = (exit_ - entry) * direction / pip_size

    diff_pct = diff.loc[events.index].to_numpy(dtype=float)
    carry_pips = direction * (diff_pct / 100.0 / 12.0) * entry / pip_size
    carry_pips = np.where(carry_pips > 0, carry_pips * swap_efficiency, carry_pips)

    return pd.DataFrame(
        {"ret": price_pips + carry_pips - cost_pips, "exit_time": close_me.index[positions + 1]},
        index=events.index,
    )
