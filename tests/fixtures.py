"""Synthetic OHLC builders for tests: a tight Asian range followed by an
engineered session sweep -> rejection -> displacement bullish reversal.
"""
from __future__ import annotations

import pandas as pd

from tradebot.config import StrategyConfig, load_default_config

ASIAN_LOW = 1.10000
ASIAN_HIGH = 1.10050


def build_session_sweep_dataframe(extra_bars_after: int = 20) -> pd.DataFrame:
    rows = []
    start = pd.Timestamp("2026-01-05T00:00:00Z")  # a Monday

    # 28 x M15 bars spanning the 00:00-07:00 UTC Asian session, flat range.
    for i in range(28):
        t = start + pd.Timedelta(minutes=15 * i)
        rows.append({"time": t, "open": 1.10025, "high": ASIAN_HIGH, "low": ASIAN_LOW, "close": 1.10025})

    # Sweep + same-bar rejection at 07:00: wick below the Asian low, closes back inside.
    sweep_time = start + pd.Timedelta(hours=7)
    rows.append(
        {"time": sweep_time, "open": 1.10015, "high": 1.10020, "low": 1.09975, "close": 1.10010}
    )

    # Displacement at 07:15: strong bullish candle confirming the reversal.
    disp_time = sweep_time + pd.Timedelta(minutes=15)
    rows.append(
        {"time": disp_time, "open": 1.10010, "high": 1.10210, "low": 1.10005, "close": 1.10200}
    )

    # Trailing bars: a further rally so a backtest has something to manage
    # the trade against (eventually hits take-profit).
    last_close = 1.10200
    for i in range(extra_bars_after):
        t = disp_time + pd.Timedelta(minutes=15 * (i + 1))
        o = last_close
        c = last_close + 0.00030
        rows.append({"time": t, "open": o, "high": c + 0.00005, "low": o - 0.00005, "close": c})
        last_close = c

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").sort_index()


def get_test_config() -> StrategyConfig:
    return load_default_config()
