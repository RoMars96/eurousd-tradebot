"""Purged, expanding-window walk-forward.

The research period is cut into `n_folds + 1` equal time chunks. For fold
k, parameters are chosen on chunks [0..k] (the past) and scored on chunk
k+1 (the future). Concatenating every fold's future-chunk trades gives an
out-of-sample record that *includes* the cost of having to pick
parameters -- the honest version of "how would this have done".

Purging: a trade only counts toward a window if its outcome was known
before that window closed (exit_time < window end), so a training trade
can't peek at prices from the test period.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradebot.research.evaluation import Summary, summarize


@dataclass
class Candidate:
    params: dict
    trades: pd.DataFrame  # index entry time, columns ret, exit_time


@dataclass
class FoldResult:
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    chosen_params: dict | None
    train_summary: Summary | None
    test_trades: pd.DataFrame


@dataclass
class WalkForwardResult:
    folds: list[FoldResult]
    oos_trades: pd.DataFrame


def _window(trades: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    mask = (trades.index >= start) & (trades["exit_time"] < end)
    return trades.loc[mask]


def select_best(
    candidates: list[Candidate], start: pd.Timestamp, end: pd.Timestamp, min_trades: int
) -> tuple[Candidate, Summary] | None:
    """Highest t-stat among candidates with at least `min_trades` in the window."""
    best: tuple[Candidate, Summary] | None = None
    for c in candidates:
        s = summarize(_window(c.trades, start, end)["ret"])
        if s.n < min_trades:
            continue
        if best is None or s.t_stat > best[1].t_stat:
            best = (c, s)
    return best


def walk_forward(
    candidates: list[Candidate],
    start: pd.Timestamp,
    end: pd.Timestamp,
    n_folds: int,
    min_trades: int,
) -> WalkForwardResult:
    edges = pd.date_range(start, end, periods=n_folds + 2)
    folds: list[FoldResult] = []
    oos_parts: list[pd.DataFrame] = []

    for k in range(1, n_folds + 1):
        train_end, test_start, test_end = edges[k], edges[k], edges[k + 1]
        best = select_best(candidates, start, train_end, min_trades)
        if best is None:
            empty = pd.DataFrame(columns=["ret", "exit_time"])
            folds.append(FoldResult(test_start, test_end, None, None, empty))
            continue
        chosen, train_summary = best
        test_trades = _window(chosen.trades, test_start, test_end)
        folds.append(FoldResult(test_start, test_end, chosen.params, train_summary, test_trades))
        oos_parts.append(test_trades)

    oos = pd.concat(oos_parts) if oos_parts else pd.DataFrame(columns=["ret", "exit_time"])
    return WalkForwardResult(folds=folds, oos_trades=oos)
