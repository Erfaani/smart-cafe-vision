from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.analytics.models import DailyStat
from apps.sessions.models import CustomerSession

pytestmark = pytest.mark.django_db


def make_session(cafe, **overrides) -> CustomerSession:
    now = timezone.now()
    defaults = {
        "cafe": cafe, "camera_id": uuid.uuid4(), "track_id": 1, "entry_at": now, "last_seen_at": now,
    }
    defaults.update(overrides)
    return CustomerSession.objects.create(**defaults)


def test_backfills_every_day_from_the_earliest_session_to_today(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    make_session(cafe, entry_at=timezone.now() - timedelta(days=3))

    call_command("backfill_daily_stats", f"--cafe={cafe.slug}")

    assert DailyStat.objects.filter(cafe=cafe).count() == 4  # 3 days ago through today, inclusive


def test_a_cafe_with_no_sessions_is_a_no_op(cafe):
    call_command("backfill_daily_stats", f"--cafe={cafe.slug}")
    assert not DailyStat.objects.filter(cafe=cafe).exists()


def test_is_idempotent_without_force(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    old_day = timezone.now().date() - timedelta(days=2)
    make_session(cafe, entry_at=timezone.now() - timedelta(days=2))
    call_command("backfill_daily_stats", f"--cafe={cafe.slug}")

    stat = DailyStat.objects.get(cafe=cafe, date=old_day)
    stat.visitor_count = 999  # simulate a hand-edited/stale row
    stat.save(update_fields=["visitor_count"])

    call_command("backfill_daily_stats", f"--cafe={cafe.slug}")

    stat.refresh_from_db()
    assert stat.visitor_count == 999  # untouched: already final, no --force


def test_force_recomputes_already_final_days(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    old_day = timezone.now().date() - timedelta(days=2)
    make_session(cafe, entry_at=timezone.now() - timedelta(days=2))
    call_command("backfill_daily_stats", f"--cafe={cafe.slug}")

    stat = DailyStat.objects.get(cafe=cafe, date=old_day)
    stat.visitor_count = 999
    stat.save(update_fields=["visitor_count"])

    call_command("backfill_daily_stats", f"--cafe={cafe.slug}", "--force")

    stat.refresh_from_db()
    assert stat.visitor_count == 1  # recomputed for real


def test_defaults_to_every_active_cafe(cafe, other_cafe):
    for c in (cafe, other_cafe):
        c.timezone = "UTC"
        c.save(update_fields=["timezone"])
    make_session(cafe, entry_at=timezone.now())
    make_session(other_cafe, entry_at=timezone.now())

    call_command("backfill_daily_stats")

    assert DailyStat.objects.filter(cafe=cafe).exists()
    assert DailyStat.objects.filter(cafe=other_cafe).exists()


def test_unknown_cafe_slug_raises(cafe):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("backfill_daily_stats", "--cafe=no-such-cafe")
