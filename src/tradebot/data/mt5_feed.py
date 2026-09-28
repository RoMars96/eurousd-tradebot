"""Live OHLC feed from a running MT5 terminal.

IMPORTANT: The `MetaTrader5` package talks to a MetaTrader 5 terminal running
on the *same machine* over local IPC -- it cannot connect to a broker over
the network by itself. This module only works when run on the Windows PC
(or Wine host) where MT5 is installed, running, and logged in to the target
account. It will raise ImportError anywhere else (e.g. this repo's CI or a
cloud dev container).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError as exc:  # pragma: no cover - exercised only off-Windows
    mt5 = None
    _import_error = exc
else:
    _import_error = None

_TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


def _require_mt5() -> None:
    if mt5 is None:
        raise ImportError(
            "MetaTrader5 package is not usable in this environment. It requires "
            "a running MT5 terminal on Windows (or Wine). Install with "
            "`pip install tradebot[mt5]` on the machine that runs the terminal."
        ) from _import_error


def connect(login: int, password: str, server: str, path: str | None = None) -> None:
    """Initialize the MT5 terminal connection and log in to an account."""
    _require_mt5()
    kwargs = {"login": login, "password": password, "server": server}
    if path:
        kwargs["path"] = path
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"MT5 initialize/login failed: {mt5.last_error()}")


def disconnect() -> None:
    if mt5 is not None:
        mt5.shutdown()


def fetch_rates(symbol: str, timeframe: str, count: int) -> pd.DataFrame:
    """Fetch the most recent `count` completed candles for symbol/timeframe."""
    _require_mt5()
    tf_attr = _TIMEFRAME_MAP.get(timeframe.upper())
    if tf_attr is None:
        raise ValueError(f"Unsupported timeframe {timeframe!r}")
    tf = getattr(mt5, tf_attr)

    rates = mt5.copy_rates_from_pos(symbol, tf, 1, count)  # skip bar 0 (still forming)
    if rates is None:
        raise RuntimeError(f"MT5 copy_rates_from_pos failed: {mt5.last_error()}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time").sort_index()
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def fetch_rates_range(
    symbol: str, timeframe: str, start: dt.datetime, end: dt.datetime
) -> pd.DataFrame:
    """Fetch all completed candles between `start` and `end` (both UTC).

    This pulls history directly from your broker through the running MT5
    terminal -- free, no third-party data provider needed. Most brokers
    carry many years of M15/M1 history for a major pair like EURUSD. MT5
    caps a single call's result set, so this pages through the range in
    chunks automatically.
    """
    _require_mt5()
    tf_attr = _TIMEFRAME_MAP.get(timeframe.upper())
    if tf_attr is None:
        raise ValueError(f"Unsupported timeframe {timeframe!r}")
    tf = getattr(mt5, tf_attr)

    if start.tzinfo is None:
        start = start.replace(tzinfo=dt.timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=dt.timezone.utc)

    chunks: list[pd.DataFrame] = []
    chunk_start = start
    chunk_span = dt.timedelta(days=180)  # comfortably under MT5's per-call bar cap

    while chunk_start < end:
        chunk_end = min(chunk_start + chunk_span, end)
        rates = mt5.copy_rates_range(symbol, tf, chunk_start, chunk_end)
        if rates is not None and len(rates):
            chunk_df = pd.DataFrame(rates)
            chunk_df["time"] = pd.to_datetime(chunk_df["time"], unit="s", utc=True)
            chunks.append(chunk_df)
        chunk_start = chunk_end

    if not chunks:
        raise RuntimeError(
            f"MT5 returned no data for {symbol} {timeframe} between {start} and {end}: "
            f"{mt5.last_error()}"
        )

    df = pd.concat(chunks, ignore_index=True)
    df = df.set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["open", "high", "low", "close", "volume"]]
