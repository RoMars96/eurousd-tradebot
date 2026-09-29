#!/usr/bin/env python3
"""Run the liquidity-sweep backtest against a historical OHLC CSV.

Usage:
    python scripts/run_backtest.py --csv path/to/eurusd_m15.csv \
        [--config config/strategy.yaml] [--trades-out trades.csv]

The CSV should have columns time/date, open, high, low, close (volume
optional) -- e.g. an MT5 "Export to CSV" of M15 history, or data from
HistData.com / Dukascopy.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradebot.backtest.engine import run_backtest
from tradebot.backtest.metrics import compute_metrics
from tradebot.config import DEFAULT_CONFIG_PATH, StrategyConfig
from tradebot.data.loader import load_ohlc_for_research


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="Path to historical OHLC CSV")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Strategy config YAML")
    parser.add_argument("--trades-out", default=None, help="Optional path to dump closed trades as CSV")
    args = parser.parse_args()

    config = StrategyConfig.from_yaml(args.config)
    df, corrected = load_ohlc_for_research(args.csv, config)
    if corrected:
        print("Detected a raw MT5 export: converted broker server time to UTC using broker_time in the config.")
    print(f"Loaded {len(df)} bars from {args.csv} ({df.index[0]} -> {df.index[-1]})")

    result = run_backtest(df, config)
    min_sample_size = config.get("backtest", "min_sample_size", default=30)
    metrics = compute_metrics(result.trades, result.equity_curve, min_sample_size=min_sample_size)

    print(f"\nSignals generated: {len(result.signals)}")
    print(f"Trades taken:       {metrics.total_trades}")
    print(f"Win rate:           {metrics.win_rate_pct:.1f}%")
    print(f"Avg R multiple:     {metrics.avg_r_multiple:.2f}")
    print(f"Expectancy (R):     {metrics.expectancy_r:.2f}")
    print(f"Profit factor:      {metrics.profit_factor:.2f}")
    print(f"Total P&L:          {metrics.total_pnl:.2f}")
    print(f"Max drawdown:       {metrics.max_drawdown_pct:.1f}%")
    print(f"Final equity:       {metrics.final_equity:.2f}")

    if not metrics.sufficient_sample:
        print(
            f"\nNOTE: only {metrics.total_trades} trade(s), below the "
            f"{metrics.min_sample_size}-trade minimum this project treats as meaningful. "
            "Per Trading in the Zone: wins and losses are randomly distributed across "
            "an edge's trades, so nothing above should be read as a verdict yet -- "
            "get more historical data before drawing conclusions."
        )

    if args.trades_out:
        import pandas as pd

        pd.DataFrame([vars(t) for t in result.trades]).to_csv(args.trades_out, index=False)
        print(f"\nWrote {len(result.trades)} trades to {args.trades_out}")


if __name__ == "__main__":
    main()
