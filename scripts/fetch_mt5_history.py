#!/usr/bin/env python3
"""Download historical OHLC data directly from your broker via MT5.

No third-party data provider needed -- MT5 gives you your broker's own
history for free once you're connected. Most brokers carry many years of
M15/M1 history for a major pair like EURUSD.

MUST be run on the Windows machine (or Wine host) where the MT5 terminal is
installed and logged in -- the MetaTrader5 package cannot connect remotely.

Usage:
    python scripts/fetch_mt5_history.py --login 12345678 --password *** \
        --server "Broker-Demo" --symbol EURUSD --timeframe M15 \
        --start 2015-01-01 --end 2026-01-01 --out eurusd_m15.csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradebot.data import mt5_feed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", type=int, required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--server", required=True, help="MT5 broker server name")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--timeframe", default="M15", choices=["M1", "M5", "M15", "M30", "H1", "H4", "D1"])
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC)")
    parser.add_argument("--out", required=True, help="Output CSV path")
    args = parser.parse_args()

    start = dt.datetime.strptime(args.start, "%Y-%m-%d")
    end = dt.datetime.strptime(args.end, "%Y-%m-%d")

    mt5_feed.connect(args.login, args.password, args.server)
    try:
        df = mt5_feed.fetch_rates_range(args.symbol, args.timeframe, start, end)
    finally:
        mt5_feed.disconnect()

    df.to_csv(args.out)
    print(f"Wrote {len(df)} {args.timeframe} bars ({df.index[0]} -> {df.index[-1]}) to {args.out}")


if __name__ == "__main__":
    main()
