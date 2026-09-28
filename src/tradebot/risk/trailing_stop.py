"""Breakeven + ATR trailing stop management.

Once a trade reaches `breakeven_trigger_r` multiples of initial risk in its
favor, the stop is moved to breakeven. Beyond that, the stop trails the most
favorable price seen by `trail_atr_multiplier` * ATR, and never loosens.
"""
from __future__ import annotations


def update_trailing_stop(
    direction: str,
    entry_price: float,
    initial_stop: float,
    current_stop: float,
    favorable_price: float,
    atr_value: float,
    breakeven_trigger_r: float,
    trail_atr_multiplier: float,
) -> float:
    """Return the (possibly tightened) stop price given the best price reached so far."""
    risk = abs(entry_price - initial_stop)
    if risk <= 0:
        return current_stop

    if direction == "long":
        r_multiple = (favorable_price - entry_price) / risk
        new_stop = current_stop
        if r_multiple >= breakeven_trigger_r:
            new_stop = max(new_stop, entry_price)
            trail_candidate = favorable_price - trail_atr_multiplier * atr_value
            new_stop = max(new_stop, trail_candidate)
        return new_stop

    if direction == "short":
        r_multiple = (entry_price - favorable_price) / risk
        new_stop = current_stop
        if r_multiple >= breakeven_trigger_r:
            new_stop = min(new_stop, entry_price)
            trail_candidate = favorable_price + trail_atr_multiplier * atr_value
            new_stop = min(new_stop, trail_candidate)
        return new_stop

    raise ValueError(f"direction must be 'long' or 'short', got {direction!r}")
