"""Liquidity-sweep reversal strategy: signal generation.

Pipeline per candidate level (a session's high/low, or a cluster of equal
swing-pivot highs/lows):

1. Sweep    -- a candle's wick pierces the level by >= min_pierce_pips.
2. Rejection -- within `rejection_max_bars`, a candle closes back inside
   (past the level, in the opposite direction of the pierce).
3. Displacement -- within `max_bars_after_rejection` bars of the rejection,
   a candle's body is >= `body_atr_multiplier` * ATR in the reversal
   direction, confirming follow-through.

A confirmed sequence produces a Signal: entry at the displacement candle's
close, direction implied by which side was swept, stop beyond the sweep's
extreme wick, take-profit at a fixed R multiple.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradebot.config import StrategyConfig
from tradebot.strategy import indicators, pivots, sessions


@dataclass(frozen=True)
class Signal:
    time: pd.Timestamp
    entry_index: int
    direction: str  # "long" or "short"
    entry_price: float
    stop_price: float
    take_profit_price: float
    level_price: float
    level_source: str
    sweep_index: int
    sweep_extreme: float
    rejection_index: int
    displacement_index: int

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.stop_price)


def _scan_sweep_rejection_displacement(
    df: pd.DataFrame,
    atr_series: pd.Series,
    level: float,
    side: str,
    start_idx: int,
    end_idx: int,
    min_pierce: float,
    rejection_max_bars: int,
    disp_multiplier: float,
    disp_max_bars: int,
) -> dict | None:
    """Scan bars [start_idx, end_idx] for the first valid sweep+rejection+displacement.

    `side` is 'low' (support level; a sweep-down sets up a long) or 'high'
    (resistance level; a sweep-up sets up a short).
    """
    n = len(df)
    end_idx = min(end_idx, n - 1)
    direction = "long" if side == "low" else "short"

    idx = max(start_idx, 0)
    while idx <= end_idx:
        bar = df.iloc[idx]
        pierced = (
            bar["low"] < (level - min_pierce)
            if side == "low"
            else bar["high"] > (level + min_pierce)
        )
        if not pierced:
            idx += 1
            continue

        sweep_index = idx
        extreme = float(bar["low"] if side == "low" else bar["high"])

        rejection_index = None
        for j in range(sweep_index, min(sweep_index + rejection_max_bars, n - 1) + 1):
            close = df.iloc[j]["close"]
            if (side == "low" and close > level) or (side == "high" and close < level):
                rejection_index = j
                break
        if rejection_index is None:
            idx = sweep_index + 1
            continue

        displacement_index = None
        for k in range(rejection_index, min(rejection_index + disp_max_bars, n - 1) + 1):
            atr_val = atr_series.iloc[k]
            if pd.isna(atr_val):
                continue
            body = df.iloc[k]["close"] - df.iloc[k]["open"]
            if direction == "long" and body >= disp_multiplier * atr_val:
                displacement_index = k
                break
            if direction == "short" and -body >= disp_multiplier * atr_val:
                displacement_index = k
                break
        if displacement_index is None:
            idx = sweep_index + 1
            continue

        return {
            "sweep_index": sweep_index,
            "extreme": extreme,
            "rejection_index": rejection_index,
            "displacement_index": displacement_index,
            "direction": direction,
        }

    return None


def _build_signal(
    df: pd.DataFrame,
    event: dict,
    level: float,
    level_source: str,
    stop_buffer: float,
    tp_r_multiple: float,
) -> Signal:
    d_idx = event["displacement_index"]
    entry_price = float(df.iloc[d_idx]["close"])
    direction = event["direction"]
    extreme = event["extreme"]

    if direction == "long":
        stop_price = extreme - stop_buffer
        risk = entry_price - stop_price
        take_profit = entry_price + tp_r_multiple * risk
    else:
        stop_price = extreme + stop_buffer
        risk = stop_price - entry_price
        take_profit = entry_price - tp_r_multiple * risk

    return Signal(
        time=df.index[d_idx],
        entry_index=d_idx,
        direction=direction,
        entry_price=entry_price,
        stop_price=float(stop_price),
        take_profit_price=float(take_profit),
        level_price=float(level),
        level_source=level_source,
        sweep_index=event["sweep_index"],
        sweep_extreme=extreme,
        rejection_index=event["rejection_index"],
        displacement_index=d_idx,
    )


def generate_signals(df: pd.DataFrame, config: StrategyConfig) -> list[Signal]:
    """Generate liquidity-sweep reversal signals over a full OHLC history.

    `df` must be a UTC-indexed OHLC frame at `config['entry_timeframe']`
    resolution, sorted ascending.
    """
    pip_size = config.get("risk", "pip_size")
    min_pierce = config.get("sweep", "min_pierce_pips") * pip_size
    rejection_max_bars = config.get("sweep", "rejection_max_bars")
    disp_multiplier = config.get("displacement", "body_atr_multiplier")
    disp_max_bars = config.get("displacement", "max_bars_after_rejection")
    stop_buffer = config.get("entry", "stop_buffer_pips") * pip_size
    tp_r_multiple = config.get("entry", "take_profit_r_multiple")
    atr_period = config.get("displacement", "atr_period")

    atr_series = indicators.atr(df, atr_period)
    n = len(df)
    signals: list[Signal] = []

    if config.get("range_detection", "use_session_range", default=True):
        horizon = config.get("range_detection", "session_search_horizon_bars", default=80)
        for name, window in config["sessions"].items():
            session_ranges = sessions.compute_session_ranges(
                df, name, window["start_hour"], window["end_hour"]
            )
            for r in session_ranges:
                start_pos = df.index.get_loc(r.end) + 1
                end_pos = start_pos + horizon

                ev = _scan_sweep_rejection_displacement(
                    df, atr_series, r.low, "low", start_pos, end_pos,
                    min_pierce, rejection_max_bars, disp_multiplier, disp_max_bars,
                )
                if ev:
                    signals.append(
                        _build_signal(df, ev, r.low, f"{name}_session", stop_buffer, tp_r_multiple)
                    )

                ev = _scan_sweep_rejection_displacement(
                    df, atr_series, r.high, "high", start_pos, end_pos,
                    min_pierce, rejection_max_bars, disp_multiplier, disp_max_bars,
                )
                if ev:
                    signals.append(
                        _build_signal(df, ev, r.high, f"{name}_session", stop_buffer, tp_r_multiple)
                    )

    if config.get("range_detection", "use_swing_pivots", default=True):
        width = config.get("range_detection", "swing_pivot_width")
        lookback = config.get("range_detection", "swing_lookback_bars")
        tol_mult = config.get("range_detection", "equal_level_tolerance_atr_mult")

        pivot_highs = pivots.find_pivot_highs(df, width)
        pivot_lows = pivots.find_pivot_lows(df, width)

        for i in range(width, n):
            atr_val = atr_series.iloc[i]
            if pd.isna(atr_val):
                continue
            tolerance = tol_mult * atr_val
            confirmed_as_of = i - 1 - width

            low_cluster = pivots.most_recent_equal_level(
                pivot_lows, tolerance, confirmed_as_of, lookback
            )
            if low_cluster:
                level, _ = low_cluster
                ev = _scan_sweep_rejection_displacement(
                    df, atr_series, level, "low", i, i,
                    min_pierce, rejection_max_bars, disp_multiplier, disp_max_bars,
                )
                if ev:
                    signals.append(
                        _build_signal(df, ev, level, "swing_pivot", stop_buffer, tp_r_multiple)
                    )

            high_cluster = pivots.most_recent_equal_level(
                pivot_highs, tolerance, confirmed_as_of, lookback
            )
            if high_cluster:
                level, _ = high_cluster
                ev = _scan_sweep_rejection_displacement(
                    df, atr_series, level, "high", i, i,
                    min_pierce, rejection_max_bars, disp_multiplier, disp_max_bars,
                )
                if ev:
                    signals.append(
                        _build_signal(df, ev, level, "swing_pivot", stop_buffer, tp_r_multiple)
                    )

    signals.sort(key=lambda s: s.entry_index)
    return signals
