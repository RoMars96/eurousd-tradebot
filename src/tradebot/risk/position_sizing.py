"""Position sizing from a fixed percent-of-equity risk model."""
from __future__ import annotations


def calculate_lots(
    equity: float,
    risk_pct: float,
    stop_distance_price: float,
    pip_size: float,
    pip_value_per_standard_lot: float,
    min_lot: float = 0.01,
    lot_step: float = 0.01,
    max_lot: float = 100.0,
) -> float:
    """Lot size such that hitting the stop loses ~`risk_pct`% of `equity`.

    `stop_distance_price` is the absolute price distance between entry and
    stop (e.g. 0.0015 for 15 pips on EUR/USD).
    """
    if stop_distance_price <= 0:
        raise ValueError("stop_distance_price must be positive")

    risk_amount = equity * (risk_pct / 100.0)
    stop_pips = stop_distance_price / pip_size
    if stop_pips <= 0:
        raise ValueError("stop distance must be greater than zero pips")

    loss_per_lot = stop_pips * pip_value_per_standard_lot
    lots = risk_amount / loss_per_lot

    lots = max(min_lot, min(max_lot, lots))
    # round down to the nearest lot step so we never risk more than intended
    steps = int(lots / lot_step)
    return round(steps * lot_step, 2)
