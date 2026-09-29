#!/usr/bin/env python3
"""Run the bot live/paper against a running MT5 terminal.

MUST be run on the Windows machine (or Wine host) where the MT5 terminal is
installed and logged in -- the MetaTrader5 package cannot connect remotely.

Usage:
    python scripts/run_live.py --mode paper --login 12345678 \
        --password *** --server "Broker-Demo" [--config config/strategy.yaml]

Start with --mode paper against a DEMO account. --mode live is gated
automatically: it refuses to start until the paper journal (see
PHILOSOPHY.md / edge_guard.min_paper_trades_before_live in the config) has
accumulated enough closed trades to judge the edge by. There is no flag to
bypass this -- it's a deliberate, code-level guardrail, not a suggestion.
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
from tradebot.journal import TradeJournal


def _journal_path(data_dir: Path, symbol: str, mode: str) -> Path:
    return data_dir / f"{mode}_journal_{symbol}.jsonl"


def _heartbeat_path(data_dir: Path, symbol: str, mode: str) -> Path:
    return data_dir / f"heartbeat_{mode}_{symbol}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["paper", "live"], required=True)
    parser.add_argument("--login", type=int, required=True, help="MT5 account login (demo or live)")
    parser.add_argument("--password", required=True)
    parser.add_argument("--server", required=True, help="MT5 broker server name")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--data-dir", default="data", help="Where trade journals are stored")
    parser.add_argument("--paper-equity", type=float, default=10000.0)
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = StrategyConfig.from_yaml(args.config)  # raises UnsafeConfigError over the ceilings
    data_dir = Path(args.data_dir)
    symbol = config["symbol"]

    if args.mode == "live":
        min_paper_trades = config.get("edge_guard", "min_paper_trades_before_live", default=30)
        paper_journal = TradeJournal(_journal_path(data_dir, symbol, "paper"))
        paper_trade_count = paper_journal.count()
        if paper_trade_count < min_paper_trades:
            print(
                f"Refusing to start in --mode live: only {paper_trade_count} paper trade(s) "
                f"recorded at {paper_journal.path}, need {min_paper_trades} before the bot will "
                "trust its own real-time performance enough to risk real money. Run --mode paper "
                "for longer first. (See PHILOSOPHY.md -- this gate is not meant to be bypassed.)"
            )
            sys.exit(1)

        confirm = input(
            "Type 'I UNDERSTAND THE RISK' to confirm you want to trade a REAL account: "
        )
        if confirm.strip() != "I UNDERSTAND THE RISK":
            print("Aborting.")
            return

    mt5_feed.connect(args.login, args.password, args.server)

    def reconnect() -> None:
        mt5_feed.disconnect()
        mt5_feed.connect(args.login, args.password, args.server)

    if args.mode == "live":
        broker = MT5Broker(symbol)
    else:
        broker = PaperBroker(args.paper_equity)

    journal_path = _journal_path(data_dir, symbol, args.mode)
    heartbeat_path = _heartbeat_path(data_dir, symbol, args.mode)
    bot = TradingBot(
        config,
        broker,
        str(journal_path),
        args.mode,
        poll_seconds=args.poll_seconds,
        heartbeat_path=str(heartbeat_path),
        reconnect_fn=reconnect,
    )
    try:
        bot.run_forever()
    finally:
        mt5_feed.disconnect()


if __name__ == "__main__":
    main()
