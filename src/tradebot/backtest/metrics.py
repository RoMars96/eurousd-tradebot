"""Summary statistics for a backtest run."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradebot.backtest.engine import Trade


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


def _max_drawdown_pct(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return float(max(0.0, -drawdown.min() * 100.0))


def compute_metrics(trades: list[Trade], equity_curve: pd.Series) -> BacktestMetrics:
    if not trades:
        final_equity = float(equity_curve.iloc[-1]) if not equity_curve.empty else 0.0
        return BacktestMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, _max_drawdown_pct(equity_curve), final_equity)

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
    )
