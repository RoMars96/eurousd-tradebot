"""Economic-calendar blackout filter.

Mechanical and non-predictive: blocks NEW entries inside a fixed window
around known high-impact economic events (NFP, FOMC/ECB rate decisions,
CPI, etc). This does not try to predict market direction from the news --
it just avoids opening trades into volatility that has nothing to do with
the liquidity-sweep setup this bot trades. See PHILOSOPHY.md. An
already-open position is never touched by this guard; only new entries are
blocked.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass

from tradebot.config import StrategyConfig
from tradebot.news.calendar_feed import CalendarCache, EconomicEvent, fetch_from_finnhub

log = logging.getLogger("tradebot.news")


@dataclass
class BlackoutStatus:
    in_blackout: bool
    reason: str


def check_blackout(
    current_time: dt.datetime,
    events: list[EconomicEvent],
    minutes_before: int,
    minutes_after: int,
) -> BlackoutStatus:
    for event in events:
        event_time = dt.datetime.fromisoformat(event.time)
        window_start = event_time - dt.timedelta(minutes=minutes_before)
        window_end = event_time + dt.timedelta(minutes=minutes_after)
        if window_start <= current_time <= window_end:
            return BlackoutStatus(
                in_blackout=True,
                reason=(
                    f"within {minutes_before}m/{minutes_after}m window of "
                    f"{event.country} '{event.event}' at {event.time}"
                ),
            )
    return BlackoutStatus(in_blackout=False, reason="no high-impact event nearby")


class NewsCalendarGuard:
    """Ties config, the Finnhub fetch, and the local cache together.

    `evaluate()` is the only method the bot needs to call each loop; it
    refreshes the cache at most once per `refresh_interval_hours` and never
    raises -- a fetch failure falls back to the last good cache, and total
    absence of any cache falls back to `fail_open_if_unavailable`.
    """

    def __init__(self, config: StrategyConfig) -> None:
        self.enabled = config.get("news_filter", "enabled", default=False)
        self.countries = config.get("news_filter", "countries", default=["US", "EU"])
        self.impact_levels = config.get("news_filter", "impact_levels", default=["high"])
        self.minutes_before = config.get("news_filter", "minutes_before", default=30)
        self.minutes_after = config.get("news_filter", "minutes_after", default=30)
        self.refresh_interval_hours = config.get("news_filter", "refresh_interval_hours", default=12)
        self.fail_open = config.get("news_filter", "fail_open_if_unavailable", default=True)
        self.lookahead_days = config.get("news_filter", "lookahead_days", default=7)

        api_key_env = config.get("news_filter", "api_key_env", default="FINNHUB_API_KEY")
        self.api_key = os.environ.get(api_key_env)

        cache_path = config.get("news_filter", "cache_path", default="data/economic_calendar_cache.json")
        self.cache = CalendarCache(cache_path)

    def _refresh_if_needed(self) -> None:
        cached = self.cache.load()
        if cached is not None:
            _, fetched_at = cached
            age = dt.datetime.now(dt.timezone.utc) - fetched_at
            if age < dt.timedelta(hours=self.refresh_interval_hours):
                return  # cache is fresh enough

        if not self.api_key:
            log.warning(
                "news_filter is enabled but no API key found (checked env var); "
                "skipping calendar refresh, will use cache/fail-open behavior"
            )
            return

        try:
            today = dt.datetime.now(dt.timezone.utc).date()
            events = fetch_from_finnhub(
                self.api_key,
                today,
                today + dt.timedelta(days=self.lookahead_days),
                self.countries,
                self.impact_levels,
            )
            self.cache.save(events)
            log.info("Refreshed economic calendar: %d high-impact event(s) cached", len(events))
        except Exception:
            log.exception("Failed to refresh economic calendar; falling back to existing cache")

    def evaluate(self, current_time: dt.datetime) -> BlackoutStatus:
        if not self.enabled:
            return BlackoutStatus(in_blackout=False, reason="news filter disabled")

        self._refresh_if_needed()
        cached = self.cache.load()

        if cached is None:
            if self.fail_open:
                return BlackoutStatus(
                    in_blackout=False,
                    reason="no calendar data available yet; failing open per config",
                )
            return BlackoutStatus(
                in_blackout=True,
                reason="no calendar data available yet; failing closed per config",
            )

        events, _ = cached
        return check_blackout(current_time, events, self.minutes_before, self.minutes_after)
