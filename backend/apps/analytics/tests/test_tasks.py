from __future__ import annotations

import uuid
import zoneinfo
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.analytics.models import DailyStat
from apps.analytics.tasks import refresh_daily_stats
from apps.sessions.models import CustomerSession

pytestmark = pytest.mark.django_db


def make_session(cafe, **overrides) -> CustomerSession:
    now = timezone.now()
    defaults = {
        "cafe": cafe, "camera_id": uuid.uuid4(), "track_id": 1, "entry_at": now, "last_seen_at": now,
    }
    defaults.update(overrides)
    return CustomerSession.objects.create(**defaults)


def local_today(cafe):
    return timezone.now().astimezone(zoneinfo.ZoneInfo(cafe.timezone)).date()


def test_refreshes_todays_row_for_every_active_cafe(cafe, other_cafe):
    make_session(cafe)
    make_session(other_cafe)

    refresh_daily_stats()

    assert DailyStat.objects.filter(cafe=cafe, date=local_today(cafe), visitor_count=1).exists()
    assert DailyStat.objects.filter(cafe=cafe, date=local_today(cafe), is_final=False).exists()
    assert DailyStat.objects.filter(cafe=other_cafe, date=local_today(other_cafe), visitor_count=1).exists()


def test_skips_a_deactivated_cafe(cafe):
    cafe.is_active = False
    cafe.save(update_fields=["is_active"])
    make_session(cafe)

    refresh_daily_stats()

    assert not DailyStat.objects.filter(cafe=cafe).exists()


def test_recomputes_yesterday_when_not_yet_final(cafe):
    """A safety net for a beat cycle landing right at local midnight --
    yesterday's row might exist but not be marked final yet."""
    yesterday = local_today(cafe) - timedelta(days=1)
    DailyStat.objects.create(cafe=cafe, date=yesterday, is_final=False, visitor_count=0)
    make_session(cafe, entry_at=timezone.now() - timedelta(days=1))

    refresh_daily_stats()

    stat = DailyStat.objects.get(cafe=cafe, date=yesterday)
    assert stat.is_final is True
    assert stat.visitor_count == 1


def test_does_not_recompute_an_already_final_yesterday(cafe):
    yesterday = local_today(cafe) - timedelta(days=1)
    DailyStat.objects.create(cafe=cafe, date=yesterday, is_final=True, visitor_count=5)
    make_session(cafe, entry_at=timezone.now() - timedelta(days=1))  # would change the count if recomputed

    refresh_daily_stats()

    stat = DailyStat.objects.get(cafe=cafe, date=yesterday)
    assert stat.visitor_count == 5  # untouched
