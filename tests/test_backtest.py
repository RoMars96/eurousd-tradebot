from fixtures import build_session_sweep_dataframe, get_test_config

from tradebot.backtest.engine import run_backtest
from tradebot.backtest.metrics import compute_metrics


def test_backtest_runs_end_to_end_and_closes_a_winning_trade():
    df = build_session_sweep_dataframe(extra_bars_after=30)
    config = get_test_config()

    result = run_backtest(df, config)

    assert result.signals, "expected the engineered sweep to produce a signal"
    assert result.trades, "expected at least one trade to have been taken"

    trade = result.trades[0]
    assert trade.direction == "long"
    assert trade.exit_reason in {"take_profit", "stop", "end_of_data"}

    metrics = compute_metrics(result.trades, result.equity_curve)
    assert metrics.total_trades == len(result.trades)
    assert metrics.final_equity == result.equity_curve.iloc[-1]


def test_metrics_on_no_trades_is_safe():
    df = build_session_sweep_dataframe()
    config = get_test_config()
    result = run_backtest(df, config)
    # Force an empty-trades path regardless of what the fixture produced.
    metrics = compute_metrics([], result.equity_curve)
    assert metrics.total_trades == 0
    assert metrics.win_rate_pct == 0.0
    assert metrics.profit_factor == 0.0
