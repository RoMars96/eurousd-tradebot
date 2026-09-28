from fixtures import ASIAN_LOW, build_session_sweep_dataframe, get_test_config

from tradebot.strategy.liquidity_sweep import generate_signals


def test_detects_bullish_asian_session_sweep():
    df = build_session_sweep_dataframe()
    config = get_test_config()

    signals = generate_signals(df, config)

    session_signals = [s for s in signals if s.level_source == "asian_session"]
    assert session_signals, "expected at least one asian_session signal"

    sig = session_signals[0]
    assert sig.direction == "long"
    assert sig.level_price == ASIAN_LOW
    assert sig.entry_price == 1.10200
    assert sig.stop_price < sig.sweep_extreme  # buffer applied beyond the wick
    assert sig.take_profit_price > sig.entry_price
    assert sig.risk > 0


def test_no_signal_when_range_never_swept():
    df = build_session_sweep_dataframe()
    # Flatten the sweep/displacement bars back into the range so nothing fires.
    df.loc[df.index[28:30], ["open", "high", "low", "close"]] = [
        [1.10025, 1.10030, 1.10020, 1.10025],
        [1.10025, 1.10030, 1.10020, 1.10025],
    ]
    config = get_test_config()

    signals = generate_signals(df, config)
    session_signals = [s for s in signals if s.level_source == "asian_session"]
    assert not session_signals
