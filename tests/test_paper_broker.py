import pandas as pd

from tradebot.execution.paper_broker import PaperBroker


def test_check_exits_reports_closed_trades_via_pop_recent_closes():
    broker = PaperBroker(starting_equity=10000)
    position = broker.open_position(
        direction="long", lots=0.1, entry_price=1.1000, stop_price=1.0980, take_profit_price=1.1040
    )

    bar = pd.Series({"open": 1.1000, "high": 1.1045, "low": 1.0995, "close": 1.1040})
    broker.check_exits(bar)

    assert broker.get_open_positions() == []
    closes = broker.pop_recent_closes()
    assert len(closes) == 1
    assert closes[0].position_id == position.id
    assert closes[0].exit_price == 1.1040
    assert closes[0].initial_stop == 1.0980

    # popped closes are cleared
    assert broker.pop_recent_closes() == []


def test_stop_hit_takes_priority_over_take_profit_same_bar():
    broker = PaperBroker(starting_equity=10000)
    broker.open_position(
        direction="long", lots=0.1, entry_price=1.1000, stop_price=1.0980, take_profit_price=1.1040
    )

    # A bar whose range covers both the stop and the take-profit.
    bar = pd.Series({"open": 1.1000, "high": 1.1050, "low": 1.0970, "close": 1.1010})
    broker.check_exits(bar)

    closes = broker.pop_recent_closes()
    assert closes[0].exit_price == 1.0980  # stop-first, conservative assumption
