"""Position sizing from a fixed percent-of-equity risk model."""
from __future__ import annotations

import logging

log = logging.getLogger("tradebot")


def calculate_lots(
    equity: float,
    risk_pct: float,
    stop_distance_price: float,
    pip_size: float,
    pip_value_per_standard_lot: float,
    min_lot: float = 0.01,
    lot_step: float = 0.01,
    max_lot: float = 100.0,
    warn_deviation_threshold: float = 1.5,
) -> float:
    """Lot size such that hitting the stop loses ~`risk_pct`% of `equity`.

    `stop_distance_price` is the absolute price distance between entry and
    stop (e.g. 0.0015 for 15 pips on EUR/USD).

    On a small account, the broker's `min_lot` floor can force the actual
    lot size above what `risk_pct` alone would call for -- a wide stop on a
    $100 account, say, might want 0.003 lots but the broker won't go below
    0.01. When that floor is what determined the size, and the resulting
    real risk is more than `warn_deviation_threshold`x the configured
    `risk_pct`, this logs a warning so that's visible rather than a silent
    surprise the first time it happens.
    """
    if stop_distance_price <= 0:
        raise ValueError("stop_distance_price must be positive")

    risk_amount = equity * (risk_pct / 100.0)
    stop_pips = stop_distance_price / pip_size
    if stop_pips <= 0:
        raise ValueError("stop distance must be greater than zero pips")

    loss_per_lot = stop_pips * pip_value_per_standard_lot
    ideal_lots = risk_amount / loss_per_lot

    lots = max(min_lot, min(max_lot, ideal_lots))
    # round down to the nearest lot step so we never risk more than intended
    steps = int(lots / lot_step)
    lots = round(steps * lot_step, 2)

    if ideal_lots < min_lot and equity > 0:
        actual_risk_pct = (lots * loss_per_lot) / equity * 100.0
        if actual_risk_pct > risk_pct * warn_deviation_threshold:
            log.warning(
                "Position size floored to min_lot=%.2f (ideal was %.4f lots): "
                "actual risk %.2f%% of equity vs configured %.2f%% -- "
                "consider a larger starting balance if this recurs often",
                min_lot,
                ideal_lots,
                actual_risk_pct,
                risk_pct,
            )

    return lots
