from __future__ import annotations

import uuid
import zoneinfo
from datetime import date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.analytics.models import DailyStat
from apps.analytics.rollups import compute_daily_stat
from apps.sessions.models import CustomerSession

pytestmark = pytest.mark.django_db


def make_session(cafe, **overrides) -> CustomerSession:
    now = timezone.now()
    defaults = {
        "cafe": cafe, "camera_id": uuid.uuid4(), "track_id": 1, "entry_at": now, "last_seen_at": now,
    }
    defaults.update(overrides)
    return CustomerSession.objects.create(**defaults)


def utc(y, m, d, h=0, mi=0, s=0) -> datetime:
    return datetime(y, m, d, h, mi, s, tzinfo=zoneinfo.ZoneInfo("UTC"))


# --------------------------------------------------------------------------- #
# visitor_count / scoping
# --------------------------------------------------------------------------- #
def test_visitor_count_counts_sessions_entering_that_local_day(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    make_session(cafe, entry_at=utc(2026, 6, 1, 10))
    make_session(cafe, entry_at=utc(2026, 6, 1, 20))

    stat = compute_daily_stat(cafe, date(2026, 6, 1))
    assert stat.visitor_count == 2


def test_visitor_count_excludes_sessions_from_other_days(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    make_session(cafe, entry_at=utc(2026, 5, 31, 23, 59))
    make_session(cafe, entry_at=utc(2026, 6, 2, 0, 0))

    stat = compute_daily_stat(cafe, date(2026, 6, 1))
    assert stat.visitor_count == 0


def test_only_the_requested_cafes_sessions_are_counted(cafe, other_cafe):
    for c in (cafe, other_cafe):
        c.timezone = "UTC"
        c.save(update_fields=["timezone"])
    make_session(cafe, entry_at=utc(2026, 6, 1, 10))
    make_session(other_cafe, entry_at=utc(2026, 6, 1, 10))

    stat = compute_daily_stat(cafe, date(2026, 6, 1))
    assert stat.visitor_count == 1


# --------------------------------------------------------------------------- #
# average / longest stay
# --------------------------------------------------------------------------- #
def test_average_and_longest_stay_use_ended_sessions_only(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    make_session(
        cafe, track_id=1, status=CustomerSession.Status.ENDED,
        entry_at=utc(2026, 6, 1, 9), exit_at=utc(2026, 6, 1, 9, 10),  # 600s
    )
    make_session(
        cafe, track_id=2, status=CustomerSession.Status.ENDED,
        entry_at=utc(2026, 6, 1, 10), exit_at=utc(2026, 6, 1, 10, 20),  # 1200s
    )
    make_session(cafe, track_id=3, entry_at=utc(2026, 6, 1, 11))  # still active, excluded

    stat = compute_daily_stat(cafe, date(2026, 6, 1))
    assert stat.ended_session_count == 2
    assert stat.total_stay_seconds == pytest.approx(1800)
    assert stat.average_stay_seconds == pytest.approx(900)
    assert stat.longest_stay_seconds == pytest.approx(1200)


def test_average_stay_is_none_with_no_ended_sessions_that_day(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    make_session(cafe, entry_at=utc(2026, 6, 1, 9))  # active

    stat = compute_daily_stat(cafe, date(2026, 6, 1))
    assert stat.average_stay_seconds is None
    assert stat.longest_stay_seconds is None
    assert stat.ended_session_count == 0


# --------------------------------------------------------------------------- #
# hourly_entries -- local time, not UTC
# --------------------------------------------------------------------------- #
def test_hourly_entries_bucket_by_local_hour(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    make_session(cafe, track_id=1, entry_at=utc(2026, 6, 1, 8))
    make_session(cafe, track_id=2, entry_at=utc(2026, 6, 1, 8, 30))
    make_session(cafe, track_id=3, entry_at=utc(2026, 6, 1, 17))

    stat = compute_daily_stat(cafe, date(2026, 6, 1))
    assert len(stat.hourly_entries) == 24
    assert stat.hourly_entries[8] == 2
    assert stat.hourly_entries[17] == 1
    assert sum(stat.hourly_entries) == 3


def test_hourly_entries_use_the_cafes_own_timezone_not_utc(cafe):
    """Asia/Tehran is UTC+03:30. A session at 21:15 UTC is 00:45 local the
    *next* calendar day -- both the bucketed hour and which day the session
    belongs to at all must follow local time."""
    cafe.timezone = "Asia/Tehran"
    cafe.save(update_fields=["timezone"])
    entry_at_utc = utc(2026, 6, 1, 21, 15)  # 00:45 local on 2026-06-02

    make_session(cafe, entry_at=entry_at_utc)

    stat_on_utc_day = compute_daily_stat(cafe, date(2026, 6, 1))
    assert stat_on_utc_day.visitor_count == 0

    stat_on_local_day = compute_daily_stat(cafe, date(2026, 6, 2))
    assert stat_on_local_day.visitor_count == 1
    assert stat_on_local_day.hourly_entries[0] == 1  # 00:45 local


# --------------------------------------------------------------------------- #
# peak_occupancy
# --------------------------------------------------------------------------- #
def test_peak_occupancy_for_non_overlapping_sessions_is_one(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    make_session(
        cafe, track_id=1, status=CustomerSession.Status.ENDED,
        entry_at=utc(2026, 6, 1, 9), exit_at=utc(2026, 6, 1, 9, 30),
    )
    make_session(
        cafe, track_id=2, status=CustomerSession.Status.ENDED,
        entry_at=utc(2026, 6, 1, 10), exit_at=utc(2026, 6, 1, 10, 30),
    )

    stat = compute_daily_stat(cafe, date(2026, 6, 1))
    assert stat.peak_occupancy == 1


def test_peak_occupancy_counts_true_overlap(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    # Three people overlap between 09:20 and 09:30.
    make_session(
        cafe, track_id=1, status=CustomerSession.Status.ENDED,
        entry_at=utc(2026, 6, 1, 9, 0), exit_at=utc(2026, 6, 1, 9, 30),
    )
    make_session(
        cafe, track_id=2, status=CustomerSession.Status.ENDED,
        entry_at=utc(2026, 6, 1, 9, 10), exit_at=utc(2026, 6, 1, 9, 40),
    )
    make_session(
        cafe, track_id=3, status=CustomerSession.Status.ENDED,
        entry_at=utc(2026, 6, 1, 9, 20), exit_at=utc(2026, 6, 1, 10, 0),
    )

    stat = compute_daily_stat(cafe, date(2026, 6, 1))
    assert stat.peak_occupancy == 3
    assert stat.peak_occupancy_at == utc(2026, 6, 1, 9, 20)


def test_peak_occupancy_treats_an_active_session_as_ongoing_until_now(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    today = timezone.now().date()
    make_session(cafe, track_id=1, entry_at=timezone.now() - timedelta(minutes=5))  # active
    make_session(cafe, track_id=2, entry_at=timezone.now() - timedelta(minutes=3))  # active

    stat = compute_daily_stat(cafe, today)
    assert stat.peak_occupancy == 2


# --------------------------------------------------------------------------- #
# is_final / idempotency
# --------------------------------------------------------------------------- #
def test_is_final_true_for_a_day_fully_in_the_past(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    stat = compute_daily_stat(cafe, date(2020, 1, 1))
    assert stat.is_final is True


def test_is_final_false_for_today(cafe):
    stat = compute_daily_stat(cafe, timezone.now().date())
    assert stat.is_final is False


def test_recomputing_upserts_rather_than_duplicating(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    day = date(2026, 6, 1)
    compute_daily_stat(cafe, day)
    make_session(cafe, entry_at=utc(2026, 6, 1, 9))
    compute_daily_stat(cafe, day)

    assert DailyStat.objects.filter(cafe=cafe, date=day).count() == 1
    assert DailyStat.objects.get(cafe=cafe, date=day).visitor_count == 1
