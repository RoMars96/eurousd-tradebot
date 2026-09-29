"""Economic calendar fetching via Finnhub's free-tier API.

IMPORTANT -- this was written and tested from a sandboxed environment with
no outbound network access, so it has NOT been verified against a live
Finnhub response. The parsing below follows Finnhub's documented schema
(https://finnhub.io/docs/api/economic-calendar) as of when this was
written, defensively (missing/unexpected fields are skipped, not fatal),
but API responses drift over time. Before trusting this for a real
blackout window, run `scripts/check_news_calendar.py` on a machine with
network access and eyeball a few known events (e.g. confirm an NFP release
lands at 08:30 America/New_York -- 12:30 or 13:30 UTC depending on DST).

Get a free API key at https://finnhub.io/register (free tier covers this
use case: a handful of calendar lookups per day).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

log = logging.getLogger("tradebot.news")

FINNHUB_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/economic"


@dataclass(frozen=True)
class EconomicEvent:
    time: str  # ISO8601 UTC
    country: str
    event: str
    impact: str


def fetch_from_finnhub(
    api_key: str,
    start: dt.date,
    end: dt.date,
    countries: list[str],
    impact_levels: list[str],
    timeout: float = 15.0,
) -> list[EconomicEvent]:
    """Fetch and filter high-impact events for a date range.

    Raises on network/HTTP failure -- callers should catch and fall back to
    a cache (see CalendarCache below) rather than let this take the bot down.
    """
    response = requests.get(
        FINNHUB_CALENDAR_URL,
        params={"from": start.isoformat(), "to": end.isoformat(), "token": api_key},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    raw_events = payload.get("economicCalendar", [])

    countries_upper = {c.upper() for c in countries}
    impacts_lower = {i.lower() for i in impact_levels}

    events: list[EconomicEvent] = []
    for item in raw_events:
        try:
            country = str(item.get("country", "")).upper()
            impact = str(item.get("impact", "")).lower()
            if countries_upper and country not in countries_upper:
                continue
            if impacts_lower and impact not in impacts_lower:
                continue

            time_raw = item.get("time")
            if not time_raw:
                continue
            # Finnhub documents this as "YYYY-MM-DD HH:MM:SS" in UTC.
            event_time = dt.datetime.strptime(time_raw, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=dt.timezone.utc
            )

            events.append(
                EconomicEvent(
                    time=event_time.isoformat(),
                    country=country,
                    event=str(item.get("event", "unknown")),
                    impact=impact,
                )
            )
        except (ValueError, TypeError) as exc:
            log.warning("Skipping malformed calendar entry %r: %s", item, exc)

    return events


class CalendarCache:
    """Local cache of fetched events so a Finnhub outage doesn't take down
    trading entirely -- economic calendars are known well in advance, so a
    cache that's a few hours stale is still directionally correct for
    near-term blackout windows.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, events: list[EconomicEvent]) -> None:
        payload = {
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "events": [asdict(e) for e in events],
        }
        self.path.write_text(json.dumps(payload))

    def load(self) -> tuple[list[EconomicEvent], dt.datetime] | None:
        """Returns (events, fetched_at) or None if there's no cache yet."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        try:
            payload = json.loads(self.path.read_text())
            fetched_at = dt.datetime.fromisoformat(payload["fetched_at"])
            events = [EconomicEvent(**e) for e in payload["events"]]
            return events, fetched_at
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            log.warning("Calendar cache at %s is corrupt, ignoring: %s", self.path, exc)
            return None
