import datetime as dt

from tradebot.config import StrategyConfig
from tradebot.news.blackout import BlackoutStatus, NewsCalendarGuard, check_blackout
from tradebot.news.calendar_feed import EconomicEvent

NFP_EVENT = EconomicEvent(
    time="2026-01-09T13:30:00+00:00", country="US", event="Nonfarm Payrolls", impact="high"
)


def test_check_blackout_inside_window():
    current_time = dt.datetime(2026, 1, 9, 13, 45, tzinfo=dt.timezone.utc)  # 15 min after
    status = check_blackout(current_time, [NFP_EVENT], minutes_before=30, minutes_after=30)
    assert status.in_blackout is True
    assert "Nonfarm Payrolls" in status.reason


def test_check_blackout_before_window():
    current_time = dt.datetime(2026, 1, 9, 13, 29, 30, tzinfo=dt.timezone.utc)  # inside 30m-before window
    status = check_blackout(current_time, [NFP_EVENT], minutes_before=30, minutes_after=30)
    assert status.in_blackout is True


def test_check_blackout_outside_window():
    current_time = dt.datetime(2026, 1, 9, 10, 0, tzinfo=dt.timezone.utc)  # hours before
    status = check_blackout(current_time, [NFP_EVENT], minutes_before=30, minutes_after=30)
    assert status.in_blackout is False


def test_check_blackout_no_events():
    current_time = dt.datetime(2026, 1, 9, 13, 30, tzinfo=dt.timezone.utc)
    status = check_blackout(current_time, [], minutes_before=30, minutes_after=30)
    assert status.in_blackout is False


def _guard_config(**news_filter_overrides) -> StrategyConfig:
    news_filter = {
        "enabled": True,
        "countries": ["US", "EU"],
        "impact_levels": ["high"],
        "minutes_before": 30,
        "minutes_after": 30,
        "refresh_interval_hours": 12,
        "fail_open_if_unavailable": True,
        "lookahead_days": 7,
        "api_key_env": "FINNHUB_API_KEY",
        "cache_path": "unused",
    }
    news_filter.update(news_filter_overrides)
    return StrategyConfig(raw={"news_filter": news_filter})


def test_guard_disabled_never_blocks(monkeypatch, tmp_path):
    config = _guard_config(enabled=False)
    guard = NewsCalendarGuard(config)
    status = guard.evaluate(dt.datetime.now(dt.timezone.utc))
    assert status.in_blackout is False
    assert "disabled" in status.reason


def test_guard_fails_open_with_no_cache_and_no_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    config = _guard_config(cache_path=str(tmp_path / "cal.json"), fail_open_if_unavailable=True)
    guard = NewsCalendarGuard(config)

    status = guard.evaluate(dt.datetime.now(dt.timezone.utc))
    assert status.in_blackout is False
    assert "fail" in status.reason.lower()


def test_guard_fails_closed_with_no_cache_and_no_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    config = _guard_config(cache_path=str(tmp_path / "cal.json"), fail_open_if_unavailable=False)
    guard = NewsCalendarGuard(config)

    status = guard.evaluate(dt.datetime.now(dt.timezone.utc))
    assert status.in_blackout is True


def test_guard_uses_existing_cache_without_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    cache_path = tmp_path / "cal.json"
    config = _guard_config(cache_path=str(cache_path))
    guard = NewsCalendarGuard(config)
    guard.cache.save([NFP_EVENT])

    inside = dt.datetime(2026, 1, 9, 13, 30, tzinfo=dt.timezone.utc)
    status = guard.evaluate(inside)
    assert status.in_blackout is True
