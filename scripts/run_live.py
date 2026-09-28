#!/usr/bin/env python3
"""Run the bot live/paper against a running MT5 terminal.

MUST be run on the Windows machine (or Wine host) where the MT5 terminal is
installed and logged in -- the MetaTrader5 package cannot connect remotely.

Usage:
    python scripts/run_live.py --mode paper --login 12345678 \
        --password *** --server "Broker-Demo" [--config config/strategy.yaml]

Start with --mode paper against a DEMO account. Only use --mode live once
you've validated the strategy via backtesting and a real-time paper run.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradebot.bot import TradingBot
from tradebot.config import DEFAULT_CONFIG_PATH, StrategyConfig
from tradebot.data import mt5_feed
from tradebot.execution.mt5_broker import MT5Broker
from tradebot.execution.paper_broker import PaperBroker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["paper", "live"], required=True)
    parser.add_argument("--login", type=int, required=True, help="MT5 account login (demo or live)")
    parser.add_argument("--password", required=True)
    parser.add_argument("--server", required=True, help="MT5 broker server name")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--paper-equity", type=float, default=10000.0)
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = StrategyConfig.from_yaml(args.config)

    mt5_feed.connect(args.login, args.password, args.server)

    if args.mode == "live":
        confirm = input(
            "Type 'I UNDERSTAND THE RISK' to confirm you want to trade a REAL account: "
        )
        if confirm.strip() != "I UNDERSTAND THE RISK":
            print("Aborting.")
            return
        broker = MT5Broker(config["symbol"])
    else:
        broker = PaperBroker(args.paper_equity)

    bot = TradingBot(config, broker, poll_seconds=args.poll_seconds)
    try:
        bot.run_forever()
    finally:
        mt5_feed.disconnect()


if __name__ == "__main__":
    main()
