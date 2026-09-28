import pytest

from tradebot.risk.position_sizing import calculate_lots
from tradebot.risk.trailing_stop import update_trailing_stop


def test_calculate_lots_risks_the_intended_percent():
    # 10,000 equity, 0.5% risk = $50 max loss. 20 pip stop, $10/pip/lot ->
    # loss per lot = $200 -> lots = 50/200 = 0.25.
    lots = calculate_lots(
        equity=10000,
        risk_pct=0.5,
        stop_distance_price=0.0020,
        pip_size=0.0001,
        pip_value_per_standard_lot=10.0,
    )
    assert lots == pytest.approx(0.25)


def test_calculate_lots_respects_min_lot_floor():
    lots = calculate_lots(
        equity=100,
        risk_pct=0.5,
        stop_distance_price=0.0020,
        pip_size=0.0001,
        pip_value_per_standard_lot=10.0,
    )
    assert lots == pytest.approx(0.01)


def test_trailing_stop_moves_to_breakeven_at_trigger():
    new_stop = update_trailing_stop(
        direction="long",
        entry_price=1.1000,
        initial_stop=1.0980,
        current_stop=1.0980,
        favorable_price=1.1020,  # exactly +1R (risk = 0.0020)
        atr_value=0.0010,
        breakeven_trigger_r=1.0,
        trail_atr_multiplier=1.0,
    )
    assert new_stop >= 1.1000


def test_trailing_stop_never_loosens_for_long():
    new_stop = update_trailing_stop(
        direction="long",
        entry_price=1.1000,
        initial_stop=1.0980,
        current_stop=1.1005,
        favorable_price=1.1002,  # pulled back from a prior better price
        atr_value=0.0010,
        breakeven_trigger_r=1.0,
        trail_atr_multiplier=1.0,
    )
    assert new_stop == pytest.approx(1.1005)


def test_trailing_stop_short_direction_trails_downward():
    new_stop = update_trailing_stop(
        direction="short",
        entry_price=1.1000,
        initial_stop=1.1020,
        current_stop=1.1020,
        favorable_price=1.0970,  # well past breakeven trigger
        atr_value=0.0010,
        breakeven_trigger_r=1.0,
        trail_atr_multiplier=1.0,
    )
    assert new_stop <= 1.1000
    assert new_stop < 1.1020
