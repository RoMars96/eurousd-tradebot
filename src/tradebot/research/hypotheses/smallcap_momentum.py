"""Hypothesis: a mechanical version of Ross Cameron's small-cap momentum
day trading has an edge after realistic slippage.

Each day at 09:30 ET, take the single biggest gapper passing the pillars
(tradebot.stocks.pillars) and trade one setup (tradebot.stocks.setups).
Trades are measured in R. The random-entry benchmark trades the same
gappers at random minutes, to separate "the setup works" from "being in
hot small caps works".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from tradebot.stocks.dataset import ET, load_day
from tradebot.stocks.pillars import scan_day, select_daily_leader
from tradebot.stocks.setups import DayBars, TradeParams, first_pullback, gap_and_go, random_entry

SETUPS = ("gap_and_go", "first_pullback")


@dataclass
class SmallcapDataset:
    scans: pd.DataFrame
    bars: dict[tuple[str, str], DayBars] = field(default_factory=dict)
    missing_days: int = 0

    @property
    def dates(self) -> pd.DatetimeIndex:
        days = sorted(self.scans["date"].unique())
        return pd.DatetimeIndex([pd.Timestamp(d, tz=ET).tz_convert("UTC") for d in days])


def load_dataset(
    directory: str | Path,
    pillars_cfg: dict,
    min_rvol_floor: float,
    log: Callable[[str], None] = lambda _: None,
) -> SmallcapDataset:
    """Scan every day; keep minute bars only for stocks that pass the
    loosest pillar settings (memory stays small)."""
    d = Path(directory)
    candidates = pd.read_csv(d / "candidates.csv", dtype={"date": str, "prev_date": str})
    ds = SmallcapDataset(scans=pd.DataFrame())
    scans = []
    for date, day in candidates.groupby("date", sort=True):
        if not (d / "minute" / f"{date}.csv.gz").exists():
            ds.missing_days += 1
            continue
        bars, news = load_day(d, date)
        s = scan_day(date, day, bars, news)
        if s.empty:
            continue
        scans.append(s)
        keep = (
            s["open_price"].between(pillars_cfg["min_price"], pillars_cfg["max_price"])
            & (s["gap_pct"] >= pillars_cfg["min_gap_pct"])
            & (s["rvol"] >= min_rvol_floor)
        )
        for symbol in s.loc[keep, "symbol"]:
            ds.bars[(date, symbol)] = DayBars(bars[bars["symbol"] == symbol])
    ds.scans = pd.concat(scans, ignore_index=True) if scans else pd.DataFrame()
    log(f"Scanned {candidates['date'].nunique() - ds.missing_days} days ({ds.missing_days} missing minute data)")
    return ds


def config_trades(
    ds: SmallcapDataset,
    setup: str,
    min_rvol: float,
    require_news: bool,
    pillars_cfg: dict,
    params: TradeParams,
    rng: np.random.Generator | None = None,
) -> pd.DataFrame:
    leaders = select_daily_leader(
        ds.scans,
        pillars_cfg["min_price"],
        pillars_cfg["max_price"],
        pillars_cfg["min_gap_pct"],
        min_rvol,
        require_news,
    )
    rows = []
    for row in leaders.itertuples(index=False):
        day = ds.bars.get((row.date, row.symbol))
        if day is None:
            continue
        if setup == "gap_and_go":
            t = gap_and_go(day, row.premarket_high, params)
        elif setup == "first_pullback":
            t = first_pullback(day, params)
        elif setup == "random":
            t = random_entry(day, rng, params)
        else:
            raise ValueError(f"unknown setup {setup!r}")
        if t is not None:
            rows.append((t.entry_time, t.r, t.exit_time, row.symbol, t.reason, t.ret_pct))

    df = pd.DataFrame(rows, columns=["entry_time", "ret", "exit_time", "symbol", "reason", "ret_pct"])
    return df.set_index("entry_time").sort_index()
