"""Summary statistics for a backtest run."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradebot.backtest.engine import Trade

DEFAULT_MIN_SAMPLE_SIZE = 30


@dataclass
class BacktestMetrics:
    total_trades: int
    win_rate_pct: float
    avg_r_multiple: float
    expectancy_r: float
    profit_factor: float
    total_pnl: float
    max_drawdown_pct: float
    final_equity: float
    sufficient_sample: bool
    min_sample_size: int


def _max_drawdown_pct(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return float(max(0.0, -drawdown.min() * 100.0))


def compute_metrics(
    trades: list[Trade],
    equity_curve: pd.Series,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> BacktestMetrics:
    """Compute performance stats.

    `sufficient_sample` flags whether `total_trades >= min_sample_size`.
    Per "Trading in the Zone": wins and losses are randomly distributed
    across a given edge's trades, so no conclusion -- good or bad -- should
    be drawn from a handful of them. Treat metrics from a small sample as
    noise, not as a verdict on the strategy.
    """
    if not trades:
        final_equity = float(equity_curve.iloc[-1]) if not equity_curve.empty else 0.0
        return BacktestMetrics(
            total_trades=0,
            win_rate_pct=0.0,
            avg_r_multiple=0.0,
            expectancy_r=0.0,
            profit_factor=0.0,
            total_pnl=0.0,
            max_drawdown_pct=_max_drawdown_pct(equity_curve),
            final_equity=final_equity,
            sufficient_sample=False,
            min_sample_size=min_sample_size,
        )

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]

    win_rate = len(wins) / len(trades) * 100.0
    avg_r = sum(t.r_multiple for t in trades) / len(trades)

    gross_profit = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in losses)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    win_rate_frac = len(wins) / len(trades)
    avg_win_r = (sum(t.r_multiple for t in wins) / len(wins)) if wins else 0.0
    avg_loss_r = (sum(t.r_multiple for t in losses) / len(losses)) if losses else 0.0
    expectancy_r = win_rate_frac * avg_win_r + (1 - win_rate_frac) * avg_loss_r

    total_pnl = sum(t.pnl for t in trades)
    final_equity = float(equity_curve.iloc[-1]) if not equity_curve.empty else 0.0

    return BacktestMetrics(
        total_trades=len(trades),
        win_rate_pct=win_rate,
        avg_r_multiple=avg_r,
        expectancy_r=expectancy_r,
        profit_factor=profit_factor,
        total_pnl=total_pnl,
        max_drawdown_pct=_max_drawdown_pct(equity_curve),
        final_equity=final_equity,
        sufficient_sample=len(trades) >= min_sample_size,
        min_sample_size=min_sample_size,
    )
