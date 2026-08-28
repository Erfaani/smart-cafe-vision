from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tables.models import TableSession
from apps.tables.tasks import close_stale_table_sessions

pytestmark = pytest.mark.django_db


def make_session(cafe, **overrides) -> TableSession:
    now = timezone.now()
    defaults = {
        "cafe": cafe, "camera_id": uuid.uuid4(), "table_zone_id": uuid.uuid4(),
        "table_name": "Table 1", "occupied_at": now, "last_seen_at": now,
    }
    defaults.update(overrides)
    return TableSession.objects.create(**defaults)


def test_closes_a_session_stale_beyond_the_grace_period(cafe, settings):
    settings.TABLE_STALE_GRACE_SECONDS = 60
    last_seen = timezone.now() - timedelta(seconds=120)
    session = make_session(cafe, last_seen_at=last_seen)

    closed = close_stale_table_sessions()

    assert closed == 1
    session.refresh_from_db()
    assert session.status == TableSession.Status.ENDED
    assert session.release_reason == TableSession.ReleaseReason.STALE
    assert session.released_at == last_seen


def test_leaves_a_recently_seen_session_active(cafe, settings):
    settings.TABLE_STALE_GRACE_SECONDS = 60
    session = make_session(cafe, last_seen_at=timezone.now())

    closed = close_stale_table_sessions()

    assert closed == 0
    session.refresh_from_db()
    assert session.status == TableSession.Status.ACTIVE


def test_does_not_touch_an_already_ended_session(cafe, settings):
    settings.TABLE_STALE_GRACE_SECONDS = 60
    old_released = timezone.now() - timedelta(days=1)
    session = make_session(
        cafe, status=TableSession.Status.ENDED,
        last_seen_at=timezone.now() - timedelta(hours=1),
        released_at=old_released, release_reason=TableSession.ReleaseReason.CLEARED,
    )

    closed = close_stale_table_sessions()

    assert closed == 0
    session.refresh_from_db()
    assert session.released_at == old_released
    assert session.release_reason == TableSession.ReleaseReason.CLEARED


def test_handles_multiple_stale_sessions_across_cafes(cafe, other_cafe, settings):
    settings.TABLE_STALE_GRACE_SECONDS = 60
    stale_at = timezone.now() - timedelta(seconds=300)
    make_session(cafe, last_seen_at=stale_at)
    make_session(other_cafe, last_seen_at=stale_at)

    closed = close_stale_table_sessions()

    assert closed == 2
    assert not TableSession.objects.filter(status=TableSession.Status.ACTIVE).exists()


def test_default_grace_period_is_used_when_setting_is_absent(cafe, settings):
    del settings.TABLE_STALE_GRACE_SECONDS
    session = make_session(cafe, last_seen_at=timezone.now() - timedelta(seconds=5))

    closed = close_stale_table_sessions()

    assert closed == 0  # 5s ago is well within the 120s default grace period
    session.refresh_from_db()
    assert session.status == TableSession.Status.ACTIVE
