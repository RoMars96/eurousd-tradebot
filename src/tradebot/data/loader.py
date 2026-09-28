"""Historical OHLC data loading.

Accepts CSV exports from MT4/MT5 ("Export to CSV" in the terminal) or common
providers like HistData / Dukascopy, after normalizing column names. The bot
does not fetch data itself here -- point it at a file you already have.
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


def load_ohlc_csv(path: str | Path, tz: str = "UTC") -> pd.DataFrame:
    """Load an OHLC CSV into a UTC DatetimeIndex-ed DataFrame.

    The returned frame has columns: open, high, low, close, and volume (if
    present), sorted ascending by time with duplicate timestamps dropped.
    """
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
