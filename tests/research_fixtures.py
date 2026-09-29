"""Synthetic GBP/JPY-like M15 data for validating the research pipeline.

`planted_edge_pips_per_bar > 0` injects a real London-reversal edge: after
price pierces the Asian range by `plant_pierce_pips` and closes back
inside, it drifts in the reversal direction for `plant_bars` bars. With it
at 0 the series is a pure random walk, where any "edge" the pipeline finds
is a false positive.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PIP = 0.01


def synthetic_gbpjpy_m15(
    n_days: int = 780,
    seed: int = 0,
    planted_edge_pips_per_bar: float = 0.0,
    plant_pierce_pips: float = 5.0,
    plant_bars: int = 16,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2021-01-04", periods=n_days, tz="UTC")
    price = 190.0
    rows = []

    for day in days:
        asian_high, asian_low = -np.inf, np.inf
        side = None
        drift_left = 0
        drift = 0.0
        for bar in range(96):
            hour = bar // 4
            vol_pips = 6.0 if hour < 7 else 14.0 if hour < 10 else 10.0
            step = rng.normal(0.0, vol_pips) * PIP
            if drift_left > 0:
                step += drift * PIP
                drift_left -= 1
            open_ = price
            close = price + step
            wick = abs(rng.normal(0.0, vol_pips * 0.5)) * PIP
            high = max(open_, close) + wick
            low = min(open_, close) - abs(rng.normal(0.0, vol_pips * 0.5)) * PIP
            price = close
            t = day + pd.Timedelta(minutes=15 * bar)
            rows.append((t, open_, high, low, close))

            if hour < 7:
                asian_high = max(asian_high, high)
                asian_low = min(asian_low, low)
            elif hour < 10 and planted_edge_pips_per_bar > 0 and drift_left == 0 and side != "done":
                pierce = plant_pierce_pips * PIP
                if side is None:
                    if high > asian_high + pierce and not low < asian_low - pierce:
                        side = "high"
                    elif low < asian_low - pierce and not high > asian_high + pierce:
                        side = "low"
                if side == "high" and close < asian_high:
                    drift, drift_left, side = -planted_edge_pips_per_bar, plant_bars, "done"
                elif side == "low" and close > asian_low:
                    drift, drift_left, side = planted_edge_pips_per_bar, plant_bars, "done"

    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"]).set_index("time")
    return df
