#!/usr/bin/env python3
"""Test a trading hypothesis for a real edge. Runs anywhere (Mac included);
no MT5 connection needed.

Usage:
    # London open vs Asian range, on M15 data:
    python scripts/research.py session-open --csv gbpjpy_m15.csv --config config/gbpjpy.yaml

    # UK-JP rate differential, on any-timeframe price data plus a rates CSV:
    python scripts/research.py carry --csv gbpjpy_d1.csv --rates uk_jp_rates.csv \
        --config config/gbpjpy.yaml

Add --reveal-holdout ONLY after a hypothesis passes, and only once. See
README "Research: looking for a real edge".

The CSV can be a raw MT5 "Export Bars" file (broker time is corrected to
UTC automatically) or a UTC CSV from scripts/fetch_mt5_history.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradebot.config import StrategyConfig
from tradebot.data.loader import load_ohlc_for_research
from tradebot.research.hypotheses.carry import load_rates_csv
from tradebot.research.log import ResearchLog
from tradebot.research.runner import format_report, run_carry, run_session_open


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("hypothesis", choices=["session-open", "carry"])
    parser.add_argument("--csv", required=True, help="Price data (MT5 export or UTC CSV)")
    parser.add_argument("--rates", help="Rates CSV (date,uk,jp) -- required for carry")
    parser.add_argument("--config", default="config/gbpjpy.yaml")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--reveal-holdout", action="store_true")
    args = parser.parse_args()

    config = StrategyConfig.from_yaml(args.config)
    df, corrected = load_ohlc_for_research(args.csv, config)
    if corrected:
        print("Detected a raw MT5 export: converted broker server time to UTC using broker_time in the config.")
    print(f"Loaded {len(df)} bars, {df.index[0]} -> {df.index[-1]}\n")

    log = ResearchLog(config.get("research", "log_path", default="data/research_log.jsonl"))
    rng = np.random.default_rng(args.seed)

    if args.hypothesis == "session-open":
        spacing = df.index.to_series().diff().median()
        if spacing.total_seconds() > 3600:
            parser.error("session-open needs intraday data (M15 or H1); this file's bars are further apart")
        report = run_session_open(df, config, Path(args.csv).name, log, rng, args.reveal_holdout)
    else:
        if not args.rates:
            parser.error("carry needs --rates")
        rates = load_rates_csv(args.rates)
        label = f"{Path(args.csv).name}+{Path(args.rates).name}"
        report = run_carry(df, rates, config, label, log, rng, args.reveal_holdout)

    print(format_report(report))


if __name__ == "__main__":
    main()
