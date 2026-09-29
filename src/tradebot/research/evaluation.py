"""Event-study evaluation: turn a hypothesis's entry signals into trades,
summarise them, and test them against null hypotheses.

A hypothesis produces *events*: a Series of +1 (long) / -1 (short) indexed
by the bar at whose close you'd enter. Each event is held for a fixed
number of bars, so the result measures the signal itself, not any stop /
target management layered on top.

A "trades" frame is indexed by entry time with columns:
    ret        net return in pips, after round-trip costs
    exit_time  when the outcome became known (used to purge leakage)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Summary:
    n: int
    mean: float
    std: float
    t_stat: float
    hit_rate: float
    total: float


def summarize(returns: pd.Series) -> Summary:
    r = returns.dropna().to_numpy(dtype=float)
    n = len(r)
    if n == 0:
        return Summary(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    mean = float(r.mean())
    std = float(r.std(ddof=1)) if n > 1 else 0.0
    if std > 0:
        t_stat = mean / (std / math.sqrt(n))
    else:
        t_stat = math.copysign(math.inf, mean) if mean != 0 else 0.0
    return Summary(n, mean, std, t_stat, float((r > 0).mean()), float(r.sum()))


def event_trades(
    close: pd.Series,
    events: pd.Series,
    horizon: int,
    pip_size: float,
    cost_pips: float,
) -> pd.DataFrame:
    """Enter at each event bar's close, exit `horizon` bars later."""
    positions = close.index.get_indexer(events.index)
    valid = (positions >= 0) & (positions + horizon < len(close))
    pos = positions[valid]
    prices = close.to_numpy(dtype=float)
    directions = events.to_numpy(dtype=float)[valid]

    gross = (prices[pos + horizon] - prices[pos]) * directions / pip_size
    return pd.DataFrame(
        {"ret": gross - cost_pips, "exit_time": close.index[pos + horizon]},
        index=events.index[valid],
    )


def sign_flip_pvalue(net_returns: pd.Series, n_perm: int, rng: np.random.Generator) -> float:
    """One-sided p-value for "mean net return > 0".

    Under the null (no edge after costs) each trade's net return is as
    likely to be positive as negative, so randomly flipping signs gives the
    null distribution of the mean.
    """
    r = net_returns.dropna().to_numpy(dtype=float)
    if len(r) == 0:
        return 1.0
    observed = r.mean()
    signs = rng.choice(np.array([-1.0, 1.0]), size=(n_perm, len(r)))
    null_means = (signs * r).mean(axis=1)
    return float((np.sum(null_means >= observed) + 1) / (n_perm + 1))


def random_timing_pvalue(
    close: pd.Series,
    events: pd.Series,
    horizon: int,
    pip_size: float,
    cost_pips: float,
    eligible_positions: np.ndarray,
    n_perm: int,
    rng: np.random.Generator,
) -> float:
    """One-sided p-value against "same trades, random timing".

    Keeps the number of trades and the long/short mix, but enters at random
    bars drawn from `eligible_positions` (e.g. the same hours of day). This
    controls for drift in the pair and for time-of-day volatility: a signal
    only passes if its *timing* beats trading those same hours at random.
    """
    trades = event_trades(close, events, horizon, pip_size, cost_pips)
    if trades.empty:
        return 1.0
    observed = trades["ret"].mean()

    prices = close.to_numpy(dtype=float)
    eligible = eligible_positions[eligible_positions + horizon < len(prices)]
    n_trades = len(trades)
    if len(eligible) < n_trades:
        return 1.0
    directions = events.loc[trades.index].to_numpy(dtype=float)

    null_means = np.empty(n_perm)
    for i in range(n_perm):
        pos = rng.choice(eligible, size=n_trades, replace=False)
        dirs = rng.permutation(directions)
        gross = (prices[pos + horizon] - prices[pos]) * dirs / pip_size
        null_means[i] = gross.mean() - cost_pips
    return float((np.sum(null_means >= observed) + 1) / (n_perm + 1))
