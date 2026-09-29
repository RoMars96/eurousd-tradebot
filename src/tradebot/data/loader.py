"""Historical OHLC data loading.

Accepts either a plain CSV (columns time/open/high/low/close, already in
UTC -- e.g. the output of scripts/fetch_mt5_history.py) or MT5's native
"Export Bars" file (tab-separated, <DATE>/<TIME>/<OPEN>... headers). The
native export is stamped in BROKER server time, not UTC: callers must run
it through tradebot.data.broker_time.correct_broker_index_to_utc, which
`load_ohlc_for_research` below does for you.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ["time", "open", "high", "low", "close"]

# Maps common column spellings from various export tools to our canonical names.
_COLUMN_ALIASES = {
    "datetime": "time",
    "date": "time",
    "timestamp": "time",
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "vol": "volume",
    "tick_volume": "volume",
}


def detect_mt5_export(path: str | Path) -> bool:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        first_line = f.readline()
    return "<DATE>" in first_line.upper()


def _parse_mt5_timestamps(dates: pd.Series, times: pd.Series | None) -> pd.Series:
    if times is None:
        return pd.to_datetime(dates, format="%Y.%m.%d", utc=True)
    combined = dates.astype(str) + " " + times.astype(str)
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
        try:
            return pd.to_datetime(combined, format=fmt, utc=True)
        except ValueError:
            continue
    raise ValueError("Unrecognised MT5 export date/time format")


def _load_mt5_export(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t", encoding="utf-8-sig")
    df.columns = [c.strip().strip("<>").lower() for c in df.columns]
    times = df["time"] if "time" in df.columns else None
    df["time"] = _parse_mt5_timestamps(df["date"], times)
    df = df.drop(columns=["date"])
    return df.rename(columns={"tickvol": "volume"})


def load_ohlc_csv(path: str | Path, tz: str = "UTC") -> pd.DataFrame:
    """Load an OHLC CSV into a DatetimeIndex-ed DataFrame.

    The returned frame has columns: open, high, low, close, and volume (if
    present), sorted ascending by time with duplicate timestamps dropped.
    For an MT5 native export the timestamps are broker time labelled as UTC
    -- see the module docstring.
    """
    if detect_mt5_export(path):
        df = _load_mt5_export(path)
    else:
        df = pd.read_csv(path)
        df.columns = [c.strip().lower() for c in df.columns]
        df = df.rename(columns={k: v for k, v in _COLUMN_ALIASES.items() if k in df.columns})

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"CSV at {path} is missing required column(s) {missing}; "
            f"found columns {list(df.columns)}"
        )

    df["time"] = pd.to_datetime(df["time"], utc=True)
    if tz != "UTC":
        df["time"] = df["time"].dt.tz_convert(tz)

    df = df.set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="first")]

    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep]


def load_ohlc_for_research(path: str | Path, config) -> tuple[pd.DataFrame, bool]:
    """Load a CSV and, if it's a raw MT5 export, correct broker time to UTC.

    Returns (df, was_corrected).
    """
    from tradebot.data.broker_time import correct_broker_index_to_utc

    df = load_ohlc_csv(path)
    if not detect_mt5_export(path):
        return df, False

    df.index = correct_broker_index_to_utc(
        df.index,
        config.get("broker_time", "utc_offset_hours_standard", default=0),
        config.get("broker_time", "utc_offset_hours_dst", default=0),
        config.get("broker_time", "dst_rule", default="none"),
    )
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df, True
