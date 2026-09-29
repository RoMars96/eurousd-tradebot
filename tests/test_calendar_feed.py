import datetime as dt

import pytest

from tradebot.news.calendar_feed import CalendarCache, EconomicEvent, fetch_from_finnhub

# A response payload shaped like Finnhub's documented economic-calendar
# schema. Since this repo's sandbox has no network access to verify a live
# response, this fixture -- not a real API call -- is what the parser is
# tested against. See calendar_feed.py's module docstring.
SAMPLE_FINNHUB_RESPONSE = {
    "economicCalendar": [
        {
            "actual": None,
            "country": "US",
            "estimate": 180000,
            "event": "Nonfarm Payrolls",
            "impact": "high",
            "prev": 175000,
            "time": "2026-01-09 13:30:00",
            "unit": "K",
        },
        {
            "actual": None,
            "country": "EU",
            "estimate": None,
            "event": "ECB Interest Rate Decision",
            "impact": "high",
            "prev": 4.0,
            "time": "2026-01-15 12:45:00",
            "unit": "%",
        },
        {
            # Low-impact event: should be filtered out by impact_levels.
            "actual": None,
            "country": "US",
            "estimate": None,
            "event": "Some Minor Indicator",
            "impact": "low",
            "prev": None,
            "time": "2026-01-10 10:00:00",
            "unit": "",
        },
        {
            # Wrong country: should be filtered out by countries.
            "actual": None,
            "country": "JP",
            "estimate": None,
            "event": "BOJ Rate Decision",
            "impact": "high",
            "prev": None,
            "time": "2026-01-11 03:00:00",
            "unit": "%",
        },
        {
            # Malformed time: should be skipped, not raise.
            "country": "US",
            "event": "Broken Entry",
            "impact": "high",
            "time": "not-a-real-timestamp",
        },
    ]
}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_from_finnhub_filters_and_parses(monkeypatch):
    def fake_get(url, params, timeout):
        assert "token" in params
        return _FakeResponse(SAMPLE_FINNHUB_RESPONSE)

    monkeypatch.setattr("tradebot.news.calendar_feed.requests.get", fake_get)

    events = fetch_from_finnhub(
        api_key="fake-key",
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 31),
        countries=["US", "EU"],
        impact_levels=["high"],
    )

    assert len(events) == 2
    assert {e.event for e in events} == {"Nonfarm Payrolls", "ECB Interest Rate Decision"}
    nfp = next(e for e in events if e.event == "Nonfarm Payrolls")
    assert nfp.time == "2026-01-09T13:30:00+00:00"
    assert nfp.country == "US"
    assert nfp.impact == "high"


def test_calendar_cache_round_trip(tmp_path):
    cache = CalendarCache(tmp_path / "calendar.json")
    assert cache.load() is None

    events = [EconomicEvent(time="2026-01-09T13:30:00+00:00", country="US", event="NFP", impact="high")]
    cache.save(events)

    loaded = cache.load()
    assert loaded is not None
    loaded_events, fetched_at = loaded
    assert loaded_events == events
    assert isinstance(fetched_at, dt.datetime)


def test_calendar_cache_handles_corrupt_file(tmp_path):
    path = tmp_path / "calendar.json"
    path.write_text("not valid json{{{")
    cache = CalendarCache(path)
    assert cache.load() is None
