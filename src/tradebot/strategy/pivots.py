"""Fractal swing-pivot detection and equal-highs/equal-lows clustering."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Pivot:
    index: int
    time: pd.Timestamp
    price: float


def find_pivot_highs(df: pd.DataFrame, width: int = 3) -> list[Pivot]:
    """A bar is a pivot high if its high is the strict max over +/- `width` bars."""
    highs = df["high"].to_numpy()
    n = len(highs)
    pivots: list[Pivot] = []
    for i in range(width, n - width):
        window = highs[i - width : i + width + 1]
        if highs[i] == window.max() and np.argmax(window) == width:
            pivots.append(Pivot(index=i, time=df.index[i], price=float(highs[i])))
    return pivots


def find_pivot_lows(df: pd.DataFrame, width: int = 3) -> list[Pivot]:
    """A bar is a pivot low if its low is the strict min over +/- `width` bars."""
    lows = df["low"].to_numpy()
    n = len(lows)
    pivots: list[Pivot] = []
    for i in range(width, n - width):
        window = lows[i - width : i + width + 1]
        if lows[i] == window.min() and np.argmin(window) == width:
            pivots.append(Pivot(index=i, time=df.index[i], price=float(lows[i])))
    return pivots


def most_recent_equal_level(
    pivots: list[Pivot], tolerance: float, as_of_index: int, lookback_bars: int
) -> tuple[float, list[Pivot]] | None:
    """Find the most recent cluster of >=2 pivots within `tolerance` of each other.

    Only pivots with index in (as_of_index - lookback_bars, as_of_index] are
    considered. Returns (level, contributing_pivots) for the cluster whose
    most recent pivot is latest, or None if no cluster of >=2 exists.
    """
    candidates = [
        p for p in pivots if as_of_index - lookback_bars <= p.index <= as_of_index
    ]
    candidates.sort(key=lambda p: p.index)

    best: tuple[float, list[Pivot]] | None = None
    for i, anchor in enumerate(candidates):
        cluster = [p for p in candidates[i:] if abs(p.price - anchor.price) <= tolerance]
        if len(cluster) >= 2:
            level = sum(p.price for p in cluster) / len(cluster)
            if best is None or cluster[-1].index >= best[1][-1].index:
                best = (level, cluster)
    return best
