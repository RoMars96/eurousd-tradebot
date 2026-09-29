#!/usr/bin/env python3
"""Smoke-test the Finnhub economic calendar integration.

Run this on a machine with network access before trusting the news
blackout filter for real trading. It fetches and prints upcoming
high-impact US/EU events so you can eyeball whether the data and, in
particular, the event *times* look right -- e.g. confirm a Nonfarm
Payrolls release lands at 08:30 America/New_York (12:30 or 13:30 UTC
depending on daylight saving).

This was written without the ability to test against a live Finnhub
response (see src/tradebot/news/calendar_feed.py's module docstring) --
this script is exactly how to close that gap yourself.

Usage:
    export FINNHUB_API_KEY=your_free_key   # https://finnhub.io/register
    python scripts/check_news_calendar.py [--config config/strategy.yaml] [--days 7]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradebot.config import DEFAULT_CONFIG_PATH, StrategyConfig
from tradebot.news.calendar_feed import fetch_from_finnhub


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    config = StrategyConfig.from_yaml(args.config)
    api_key_env = config.get("news_filter", "api_key_env", default="FINNHUB_API_KEY")
    api_key = os.environ.get(api_key_env)
    if not api_key:
        print(f"Set the {api_key_env} environment variable first (get a free key at https://finnhub.io/register)")
        sys.exit(1)

    countries = config.get("news_filter", "countries", default=["US", "EU"])
    impact_levels = config.get("news_filter", "impact_levels", default=["high"])
    today = dt.datetime.now(dt.timezone.utc).date()

    events = fetch_from_finnhub(api_key, today, today + dt.timedelta(days=args.days), countries, impact_levels)

    if not events:
        print(
            "No events returned. Either it's a quiet week, or the response schema has drifted "
            "from what calendar_feed.py expects -- check the raw response manually if this is "
            "surprising."
        )
        return

    print(f"{'Time (UTC)':<26} {'Country':<8} {'Impact':<8} Event")
    for e in sorted(events, key=lambda e: e.time):
        print(f"{e.time:<26} {e.country:<8} {e.impact:<8} {e.event}")


if __name__ == "__main__":
    main()
