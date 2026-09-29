import datetime as dt

import pandas as pd

from tradebot.data.broker_time import (
    broker_utc_offset_hours,
    correct_broker_index_to_utc,
)


def test_standard_offset_outside_dst_window():
    # Mid-January: well outside EU DST.
    moment = dt.datetime(2026, 1, 15, 12, 0, tzinfo=dt.timezone.utc)
    assert broker_utc_offset_hours(moment, standard_offset_hours=2, dst_offset_hours=3, dst_rule="eu") == 2


def test_dst_offset_inside_dst_window():
    # Mid-July: well inside EU DST.
    moment = dt.datetime(2026, 7, 15, 12, 0, tzinfo=dt.timezone.utc)
    assert broker_utc_offset_hours(moment, standard_offset_hours=2, dst_offset_hours=3, dst_rule="eu") == 3


def test_dst_boundary_last_sunday_of_march_2026():
    # 2026-03-29 is the last Sunday of March 2026.
    before_transition = dt.datetime(2026, 3, 29, 0, 59, tzinfo=dt.timezone.utc)
    after_transition = dt.datetime(2026, 3, 29, 1, 1, tzinfo=dt.timezone.utc)
    assert broker_utc_offset_hours(before_transition, 2, 3, "eu") == 2
    assert broker_utc_offset_hours(after_transition, 2, 3, "eu") == 3


def test_dst_boundary_last_sunday_of_october_2026():
    # 2026-10-25 is the last Sunday of October 2026.
    before_transition = dt.datetime(2026, 10, 25, 0, 59, tzinfo=dt.timezone.utc)
    after_transition = dt.datetime(2026, 10, 25, 1, 1, tzinfo=dt.timezone.utc)
    assert broker_utc_offset_hours(before_transition, 2, 3, "eu") == 3
    assert broker_utc_offset_hours(after_transition, 2, 3, "eu") == 2


def test_none_dst_rule_always_uses_standard_offset():
    summer = dt.datetime(2026, 7, 15, tzinfo=dt.timezone.utc)
    assert broker_utc_offset_hours(summer, standard_offset_hours=5, dst_offset_hours=99, dst_rule="none") == 5


def test_correct_broker_index_to_utc_shifts_timestamps():
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-01-15 10:00:00", tz="UTC"),  # standard offset (2h)
            pd.Timestamp("2026-07-15 10:00:00", tz="UTC"),  # dst offset (3h)
        ]
    )
    corrected = correct_broker_index_to_utc(index, standard_offset_hours=2, dst_offset_hours=3, dst_rule="eu")

    assert corrected[0] == pd.Timestamp("2026-01-15 08:00:00", tz="UTC")
    assert corrected[1] == pd.Timestamp("2026-07-15 07:00:00", tz="UTC")


def test_correct_broker_index_to_utc_noop_when_zero_offset():
    index = pd.DatetimeIndex([pd.Timestamp("2026-01-15 10:00:00", tz="UTC")])
    corrected = correct_broker_index_to_utc(index, standard_offset_hours=0, dst_offset_hours=0, dst_rule="none")
    assert corrected.equals(index)
