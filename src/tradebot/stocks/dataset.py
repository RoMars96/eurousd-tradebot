"""Build and load the small-cap gapper dataset.

Layout under the data directory (resumable -- rerunning skips finished work):
    candidates.csv          one row per (date, symbol) daily-bar gapper
    minute/<date>.csv.gz    1-minute bars 04:00-11:00 ET for that day's candidates
    news/<date>.json        headlines from the prior close to 09:30 ET

Two traps handled here:
- Reverse splits, very common in small caps, look like enormous "gaps" in
  raw prices. A candidate is only kept if the raw/split-adjusted price
  ratio was constant over the 21 days up to and including it.
- Survivorship: the symbol universe includes inactive (delisted) assets,
  so stocks that later went bust still appear in history.

The daily-bar gap is only a coarse prefilter (looser than the real scan);
the real 09:30 scan in pillars.py recomputes everything from minute bars.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")


def et_timestamp(date: str, hhmm: str) -> pd.Timestamp:
    hour, minute = (int(x) for x in hhmm.split(":"))
    d = dt.date.fromisoformat(date)
    return pd.Timestamp(dt.datetime(d.year, d.month, d.day, hour, minute, tzinfo=ET)).tz_convert("UTC")


def tradable_symbols(assets: list[dict]) -> list[str]:
    return sorted({a["symbol"] for a in assets if a.get("exchange") != "OTC" and a.get("symbol")})


def find_candidates(
    raw: pd.DataFrame,
    adj: pd.DataFrame,
    min_gap_pct: float,
    min_price: float,
    max_price: float,
) -> pd.DataFrame:
    """Daily-bar gappers: gap >= min_gap_pct, prior close in price range,
    no split in the trailing 21 days, and a full 20-day volume average."""
    cols = ["date", "prev_date", "symbol", "prev_close", "daily_open", "gap_pct", "adv20"]
    if raw.empty or adj.empty:
        return pd.DataFrame(columns=cols)

    m = raw.merge(
        adj[["symbol", "time", "close"]].rename(columns={"close": "adj_close"}),
        on=["symbol", "time"],
        how="inner",
    ).sort_values(["symbol", "time"])
    m["date"] = m["time"].dt.tz_convert(ET).dt.strftime("%Y-%m-%d")

    g = m.groupby("symbol", sort=False)
    m["prev_close"] = g["close"].shift(1)
    m["prev_date"] = g["date"].shift(1)
    m["gap_pct"] = (m["open"] / m["prev_close"] - 1.0) * 100.0

    m["factor"] = m["close"] / m["adj_close"]
    fmax = g["factor"].transform(lambda s: s.rolling(21, min_periods=21).max())
    fmin = g["factor"].transform(lambda s: s.rolling(21, min_periods=21).min())
    split_free = (fmax / fmin - 1.0).abs() < 0.001
    m["adv20"] = g["volume"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())

    mask = (
        (m["gap_pct"] >= min_gap_pct)
        & m["prev_close"].between(min_price, max_price)
        & split_free
        & (m["adv20"] > 0)
    )
    return m.loc[mask].rename(columns={"open": "daily_open"})[cols].reset_index(drop=True)


def top_per_day(candidates: pd.DataFrame, n: int) -> pd.DataFrame:
    ranked = candidates.sort_values(["date", "gap_pct"], ascending=[True, False])
    return ranked.groupby("date", sort=True).head(n).reset_index(drop=True)


def _atomic_write(path: Path, write: Callable[[Path], None]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    write(tmp)
    os.replace(tmp, path)


def fetch_dataset(
    client,
    data_cfg: dict,
    directory: str | Path,
    start: dt.date,
    end: dt.date,
    log: Callable[[str], None] = print,
    batch_size: int = 400,
) -> Path:
    d = Path(directory)
    (d / "minute").mkdir(parents=True, exist_ok=True)
    (d / "news").mkdir(parents=True, exist_ok=True)
    cand_path = d / "candidates.csv"

    if cand_path.exists():
        candidates = pd.read_csv(cand_path, dtype={"date": str, "prev_date": str})
        log(f"Using existing {cand_path} ({len(candidates)} candidates)")
    else:
        symbols = tradable_symbols(client.assets())
        log(f"{len(symbols)} symbols (active + delisted, excluding OTC)")
        lookback_start = pd.Timestamp(start - dt.timedelta(days=45), tz=ET)
        end_ts = pd.Timestamp(end + dt.timedelta(days=1), tz=ET)
        parts = []
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            raw = client.bars(batch, "1Day", lookback_start, end_ts, adjustment="raw")
            adj = client.bars(batch, "1Day", lookback_start, end_ts, adjustment="split")
            found = find_candidates(
                raw,
                adj,
                data_cfg.get("prefilter_min_gap_pct", 8.0),
                data_cfg.get("prefilter_min_price", 1.5),
                data_cfg.get("prefilter_max_price", 25.0),
            )
            parts.append(found[found["date"] >= start.isoformat()])
            log(f"  daily bars {min(i + batch_size, len(symbols))}/{len(symbols)} symbols scanned")
        candidates = top_per_day(pd.concat(parts, ignore_index=True), data_cfg.get("max_candidates_per_day", 20))
        _atomic_write(cand_path, lambda p: candidates.to_csv(p, index=False))
        log(f"Saved {len(candidates)} candidates over {candidates['date'].nunique()} days")

    window_start, window_end = data_cfg.get("minute_window_et", ["04:00", "11:00"])
    dates = sorted(candidates["date"].unique())
    for n, date in enumerate(dates, 1):
        day = candidates[candidates["date"] == date]
        symbols = sorted(day["symbol"].unique())

        minute_path = d / "minute" / f"{date}.csv.gz"
        if not minute_path.exists():
            bars = client.bars(symbols, "1Min", et_timestamp(date, window_start), et_timestamp(date, window_end))
            _atomic_write(minute_path, lambda p: bars.to_csv(p, index=False, compression="gzip"))

        news_path = d / "news" / f"{date}.json"
        if not news_path.exists():
            items = client.news(symbols, et_timestamp(day["prev_date"].min(), "16:00"), et_timestamp(date, "09:30"))
            _atomic_write(news_path, lambda p: p.write_text(json.dumps(items)))

        if n % 25 == 0 or n == len(dates):
            log(f"  intraday data {n}/{len(dates)} days")
    return d


def load_day(directory: str | Path, date: str) -> tuple[pd.DataFrame, list[dict]]:
    d = Path(directory)
    bars = pd.read_csv(d / "minute" / f"{date}.csv.gz")
    bars["time"] = pd.to_datetime(bars["time"], utc=True)
    news_path = d / "news" / f"{date}.json"
    news = json.loads(news_path.read_text()) if news_path.exists() else []
    return bars, news
