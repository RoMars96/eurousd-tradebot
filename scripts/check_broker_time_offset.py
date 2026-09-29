#!/usr/bin/env python3
"""Verify the broker_time config against your actual MT5 connection.

This bot corrects MT5's broker-server-time candle timestamps to true UTC
(see src/tradebot/data/broker_time.py) using a configured offset -- but
that offset was written without the ability to test it against a live
connection (see the module's docstring). Run this on the machine with MT5
installed and logged in to check it before trusting any session-based
signal on real data.

What it does: fetches the single most recent tick, compares MT5's
timestamp for it against your system clock's real UTC time right now, and
tells you whether the currently configured broker_time offset in
config/strategy.yaml looks right.

Usage:
    python scripts/check_broker_time_offset.py --login 12345678 \
        --password *** --server "ICMarkets-Demo" [--config config/strategy.yaml]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradebot.config import DEFAULT_CONFIG_PATH, StrategyConfig
from tradebot.data import mt5_feed
from tradebot.data.broker_time import broker_utc_offset_hours

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", type=int, required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--symbol", default=None, help="Defaults to config['symbol']")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    args = parser.parse_args()

    config = StrategyConfig.from_yaml(args.config)
    symbol = args.symbol or config["symbol"]

    standard_offset = config.get("broker_time", "utc_offset_hours_standard", default=0)
    dst_offset = config.get("broker_time", "utc_offset_hours_dst", default=0)
    dst_rule = config.get("broker_time", "dst_rule", default="none")

    mt5_feed.connect(args.login, args.password, args.server)
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            print(f"Could not get a tick for {symbol}: {mt5.last_error()}")
            sys.exit(1)

        server_labeled_time = dt.datetime.fromtimestamp(tick.time, tz=dt.timezone.utc)
        real_utc_now = dt.datetime.now(dt.timezone.utc)
        raw_diff_hours = (server_labeled_time - real_utc_now).total_seconds() / 3600.0

        configured_offset = broker_utc_offset_hours(real_utc_now, standard_offset, dst_offset, dst_rule)

        print(f"Real UTC now:                    {real_utc_now.isoformat()}")
        print(f"MT5's tick timestamp (unconverted): {server_labeled_time.isoformat()}")
        print(f"=> broker clock appears to be ~{raw_diff_hours:+.2f}h from true UTC "
              f"(some of this is normal tick-arrival latency, expect it close to a whole number)")
        print(f"Configured offset right now (broker_time in {args.config}): {configured_offset:+d}h "
              f"(standard={standard_offset:+d}h, dst={dst_offset:+d}h, dst_rule={dst_rule})")

        rounded_diff = round(raw_diff_hours)
        if abs(raw_diff_hours - rounded_diff) > 0.25:
            print("\nNOTE: the observed offset isn't close to a whole number of hours -- "
                  "that's more than normal tick latency should cause. Double check.")
        elif rounded_diff != configured_offset:
            print(
                f"\nMISMATCH: observed offset (~{rounded_diff:+d}h) does not match the configured "
                f"offset ({configured_offset:+d}h). Update broker_time in your config before "
                "trusting session-based signals."
            )
        else:
            print("\nLooks consistent with the configured offset.")
    finally:
        mt5_feed.disconnect()


if __name__ == "__main__":
    main()
