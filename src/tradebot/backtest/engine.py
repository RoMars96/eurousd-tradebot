"""Bar-by-bar backtest simulation for the liquidity-sweep strategy.

Simplifying assumptions (documented so results aren't over-trusted):
- Single timeframe: trade management uses the same bars as signal generation.
- If a bar's range contains both the stop and the take-profit, the stop is
  assumed to fill first (conservative).
- Spread + slippage are modeled as a fixed round-trip pip cost per trade,
  not as separate bid/ask price paths.
- Trades still open at the end of the data are force-closed at the final
  candle's close.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradebot.config import StrategyConfig
from tradebot.risk.guard import RiskGuard
from tradebot.risk.position_sizing import calculate_lots
from tradebot.risk.trailing_stop import update_trailing_stop
from tradebot.strategy import indicators
from tradebot.strategy.liquidity_sweep import Signal, generate_signals


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: str
    entry_price: float
    exit_price: float
    initial_stop: float
    take_profit_price: float
    lots: float
    pnl: float
    r_multiple: float
    exit_reason: str
    level_source: str


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series
    signals: list[Signal]


def run_backtest(df: pd.DataFrame, config: StrategyConfig) -> BacktestResult:
    signals = generate_signals(df, config)

    pip_size = config.get("risk", "pip_size")
    pip_value = config.get("risk", "pip_value_per_standard_lot")
    risk_pct = config.get("risk", "risk_per_trade_pct")
    max_concurrent = config.get("risk", "max_concurrent_positions")
    daily_loss_limit = config.get("risk", "daily_loss_limit_pct")

    round_trip_cost_pips = config.get("backtest", "spread_pips", default=0.0) + config.get(
        "backtest", "slippage_pips", default=0.0
    )
    starting_equity = config.get("backtest", "starting_equity", default=10000.0)

    trailing_enabled = config.get("trailing_stop", "enabled", default=True)
    be_trigger = config.get("trailing_stop", "breakeven_trigger_r")
    trail_mult = config.get("trailing_stop", "trail_atr_multiplier")
    atr_period = config.get("displacement", "atr_period")
    atr_series = indicators.atr(df, atr_period)

    guard = RiskGuard(daily_loss_limit, max_concurrent)
    equity = starting_equity
    equity_curve_index: list[pd.Timestamp] = []
    equity_curve_values: list[float] = []
    open_trades: list[dict] = []
    closed_trades: list[Trade] = []

    signals_by_index: dict[int, list[Signal]] = {}
    for s in signals:
        signals_by_index.setdefault(s.entry_index, []).append(s)

    n = len(df)

    def _close(tr: dict, exit_price: float, exit_reason: str, exit_time: pd.Timestamp) -> None:
        nonlocal equity
        direction = tr["direction"]
        pip_diff = (
            (exit_price - tr["entry_price"]) / pip_size
            if direction == "long"
            else (tr["entry_price"] - exit_price) / pip_size
        )
        pip_diff -= round_trip_cost_pips
        pnl = pip_diff * pip_value * tr["lots"]
        equity += pnl
        r_multiple = (pip_diff * pip_size) / tr["risk"] if tr["risk"] > 0 else 0.0
        closed_trades.append(
            Trade(
                entry_time=tr["entry_time"],
                exit_time=exit_time,
                direction=direction,
                entry_price=tr["entry_price"],
                exit_price=exit_price,
                initial_stop=tr["initial_stop"],
                take_profit_price=tr["take_profit_price"],
                lots=tr["lots"],
                pnl=pnl,
                r_multiple=r_multiple,
                exit_reason=exit_reason,
                level_source=tr["level_source"],
            )
        )

    for i in range(n):
        t = df.index[i]
        bar = df.iloc[i]
        guard.roll_day(t, equity)

        still_open = []
        for tr in open_trades:
            direction = tr["direction"]
            if direction == "long":
                tr["best_price"] = max(tr["best_price"], bar["high"])
            else:
                tr["best_price"] = min(tr["best_price"], bar["low"])

            if trailing_enabled:
                atr_val = atr_series.iloc[i]
                if not pd.isna(atr_val):
                    tr["stop_price"] = update_trailing_stop(
                        direction,
                        tr["entry_price"],
                        tr["initial_stop"],
                        tr["stop_price"],
                        tr["best_price"],
                        atr_val,
                        be_trigger,
                        trail_mult,
                    )

            exit_price = None
            exit_reason = None
            if direction == "long":
                if bar["low"] <= tr["stop_price"]:
                    exit_price, exit_reason = tr["stop_price"], "stop"
                elif bar["high"] >= tr["take_profit_price"]:
                    exit_price, exit_reason = tr["take_profit_price"], "take_profit"
            else:
                if bar["high"] >= tr["stop_price"]:
                    exit_price, exit_reason = tr["stop_price"], "stop"
                elif bar["low"] <= tr["take_profit_price"]:
                    exit_price, exit_reason = tr["take_profit_price"], "take_profit"

            if exit_price is not None:
                _close(tr, exit_price, exit_reason, t)
            else:
                still_open.append(tr)
        open_trades = still_open

        guard.register_equity(t, equity)
        equity_curve_index.append(t)
        equity_curve_values.append(equity)

        for sig in signals_by_index.get(i, []):
            if not guard.can_open_position(len(open_trades)):
                continue
            stop_distance = sig.risk
            lots = calculate_lots(equity, risk_pct, stop_distance, pip_size, pip_value)
            open_trades.append(
                {
                    "direction": sig.direction,
                    "entry_price": sig.entry_price,
                    "initial_stop": sig.stop_price,
                    "stop_price": sig.stop_price,
                    "take_profit_price": sig.take_profit_price,
                    "lots": lots,
                    "risk": stop_distance,
                    "best_price": sig.entry_price,
                    "entry_time": t,
                    "level_source": sig.level_source,
                }
            )

    if open_trades and n > 0:
        last_time = df.index[-1]
        last_close = float(df.iloc[-1]["close"])
        for tr in open_trades:
            _close(tr, last_close, "end_of_data", last_time)

    equity_curve = pd.Series(equity_curve_values, index=pd.Index(equity_curve_index), name="equity")
    return BacktestResult(trades=closed_trades, equity_curve=equity_curve, signals=signals)
