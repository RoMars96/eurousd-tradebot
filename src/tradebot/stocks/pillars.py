"""The 09:30 ET scan: a mechanical reading of Ross Cameron's "Five Pillars".

Measured using only data available at 09:30:
    price       09:30 open, within [min_price, max_price]
    gap         09:30 open vs prior close
    rel. volume premarket volume (04:00-09:29) / prior 20-day average daily volume
    news        any headline for the symbol between prior close and 09:30

Float (the fifth pillar) isn't available from Alpaca and is left out --
a known gap between this test and his discretionary selection.
"""
from __future__ import annotations

import pandas as pd

from tradebot.stocks.dataset import ET, et_timestamp

PREMARKET_START = 4 * 60
OPEN = 9 * 60 + 30


def et_minutes(times: pd.Series) -> pd.Series:
    et = times.dt.tz_convert(ET)
    return et.dt.hour * 60 + et.dt.minute


def scan_day(date: str, candidates: pd.DataFrame, bars: pd.DataFrame, news: list[dict]) -> pd.DataFrame:
    news_times = [(pd.Timestamp(n["created_at"]).tz_convert("UTC"), set(n.get("symbols") or [])) for n in news]
    cutoff = et_timestamp(date, "09:30")

    rows = []
    for c in candidates.itertuples(index=False):
        sub = bars[bars["symbol"] == c.symbol]
        if sub.empty:
            continue
        minutes = et_minutes(sub["time"])
        open_bar = sub[minutes == OPEN]
        if open_bar.empty:
            continue
        pm = sub[(minutes >= PREMARKET_START) & (minutes < OPEN)]
        open_price = float(open_bar["open"].iloc[0])
        news_start = et_timestamp(c.prev_date, "16:00")
        has_news = any(news_start < t <= cutoff and c.symbol in syms for t, syms in news_times)

        rows.append(
            {
                "date": date,
                "symbol": c.symbol,
                "prev_close": float(c.prev_close),
                "open_price": open_price,
                "gap_pct": (open_price / float(c.prev_close) - 1.0) * 100.0,
                "premarket_volume": float(pm["volume"].sum()),
                "premarket_high": float(pm["high"].max()) if not pm.empty else float("nan"),
                "adv20": float(c.adv20),
                "rvol": float(pm["volume"].sum()) / float(c.adv20),
                "has_news": has_news,
            }
        )
    return pd.DataFrame(rows)


def select_daily_leader(
    scans: pd.DataFrame,
    min_price: float,
    max_price: float,
    min_gap_pct: float,
    min_rvol: float,
    require_news: bool,
) -> pd.DataFrame:
    """Stocks passing the pillars, then the single biggest gapper per day
    -- a small account holds one position at a time."""
    ok = (
        scans["open_price"].between(min_price, max_price)
        & (scans["gap_pct"] >= min_gap_pct)
        & (scans["rvol"] >= min_rvol)
    )
    if require_news:
        ok &= scans["has_news"]
    passed = scans[ok].sort_values(["date", "gap_pct"], ascending=[True, False])
    return passed.groupby("date", sort=True).head(1).reset_index(drop=True)
