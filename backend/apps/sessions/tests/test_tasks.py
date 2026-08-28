from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.sessions.models import CustomerSession
from apps.sessions.tasks import close_stale_sessions

pytestmark = pytest.mark.django_db


def make_session(cafe, **overrides) -> CustomerSession:
    now = timezone.now()
    defaults = {
        "cafe": cafe,
        "camera_id": uuid.uuid4(),
        "track_id": 1,
        "entry_at": now,
        "last_seen_at": now,
    }
    defaults.update(overrides)
    return CustomerSession.objects.create(**defaults)


def test_closes_a_session_stale_beyond_the_grace_period(cafe, settings):
    settings.SESSION_STALE_GRACE_SECONDS = 60
    last_seen = timezone.now() - timedelta(seconds=120)
    session = make_session(cafe, last_seen_at=last_seen)

    closed = close_stale_sessions()

    assert closed == 1
    session.refresh_from_db()
    assert session.status == CustomerSession.Status.ENDED
    assert session.exit_reason == CustomerSession.ExitReason.TRACK_LOST
    assert session.exit_at == last_seen  # best estimate: when it was last seen, not now


def test_leaves_a_recently_seen_session_active(cafe, settings):
    settings.SESSION_STALE_GRACE_SECONDS = 60
    session = make_session(cafe, last_seen_at=timezone.now())

    closed = close_stale_sessions()

    assert closed == 0
    session.refresh_from_db()
    assert session.status == CustomerSession.Status.ACTIVE


def test_does_not_touch_an_already_ended_session(cafe, settings):
    settings.SESSION_STALE_GRACE_SECONDS = 60
    old_exit = timezone.now() - timedelta(days=1)
    session = make_session(
        cafe,
        status=CustomerSession.Status.ENDED,
        last_seen_at=timezone.now() - timedelta(hours=1),
        exit_at=old_exit,
        exit_reason=CustomerSession.ExitReason.LINE_CROSSING,
    )

    closed = close_stale_sessions()

    assert closed == 0
    session.refresh_from_db()
    assert session.exit_at == old_exit
    assert session.exit_reason == CustomerSession.ExitReason.LINE_CROSSING


def test_handles_multiple_stale_sessions_across_cafes(cafe, other_cafe, settings):
    settings.SESSION_STALE_GRACE_SECONDS = 60
    stale_at = timezone.now() - timedelta(seconds=300)
    make_session(cafe, last_seen_at=stale_at)
    make_session(other_cafe, last_seen_at=stale_at)

    closed = close_stale_sessions()

    assert closed == 2
    assert not CustomerSession.objects.filter(status=CustomerSession.Status.ACTIVE).exists()


def test_default_grace_period_is_used_when_setting_is_absent(cafe, settings):
    """Regression guard for the getattr(settings, ..., DEFAULT) fallback --
    must not raise even if SESSION_STALE_GRACE_SECONDS were ever removed from
    settings."""
    del settings.SESSION_STALE_GRACE_SECONDS
    session = make_session(cafe, last_seen_at=timezone.now() - timedelta(seconds=5))

    closed = close_stale_sessions()

    assert closed == 0  # 5s ago is well within the 120s default grace period
    session.refresh_from_db()
    assert session.status == CustomerSession.Status.ACTIVE
