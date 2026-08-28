from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.events.models import TrackingEvent
from apps.events.tasks import prune_old_events

pytestmark = pytest.mark.django_db


def make_event(cafe, **overrides) -> TrackingEvent:
    now = timezone.now()
    defaults = {
        "cafe": cafe,
        "event_type": "worker_heartbeat",
        "event_id": uuid.uuid4(),
        "occurred_at": now,
    }
    defaults.update(overrides)
    return TrackingEvent.objects.create(**defaults)


def test_deletes_an_event_older_than_the_retention_window(cafe, settings):
    settings.EVENT_RETENTION_DAYS = 90
    old = make_event(cafe, occurred_at=timezone.now() - timedelta(days=91))

    deleted = prune_old_events()

    assert deleted == 1
    assert not TrackingEvent.objects.filter(pk=old.pk).exists()


def test_leaves_a_recent_event_alone(cafe, settings):
    settings.EVENT_RETENTION_DAYS = 90
    recent = make_event(cafe, occurred_at=timezone.now() - timedelta(days=1))

    deleted = prune_old_events()

    assert deleted == 0
    assert TrackingEvent.objects.filter(pk=recent.pk).exists()


def test_an_event_exactly_at_the_boundary_is_kept(cafe, settings, monkeypatch):
    """occurred_at__lt, not __lte -- an event exactly at the cutoff is not yet
    past its retention window. The task's own `timezone.now()` is frozen so
    the comparison is exact rather than racing the real clock by a few
    microseconds."""
    settings.EVENT_RETENTION_DAYS = 90
    frozen_now = timezone.now()
    monkeypatch.setattr("apps.events.tasks.timezone.now", lambda: frozen_now)
    boundary = make_event(cafe, occurred_at=frozen_now - timedelta(days=90))

    deleted = prune_old_events()

    assert deleted == 0
    assert TrackingEvent.objects.filter(pk=boundary.pk).exists()


def test_zero_retention_disables_pruning(cafe, settings):
    settings.EVENT_RETENTION_DAYS = 0
    make_event(cafe, occurred_at=timezone.now() - timedelta(days=3650))

    deleted = prune_old_events()

    assert deleted == 0
    assert TrackingEvent.objects.count() == 1


def test_handles_events_across_multiple_cafes(cafe, other_cafe, settings):
    settings.EVENT_RETENTION_DAYS = 90
    stale_at = timezone.now() - timedelta(days=91)
    make_event(cafe, occurred_at=stale_at)
    make_event(other_cafe, occurred_at=stale_at)

    deleted = prune_old_events()

    assert deleted == 2
    assert TrackingEvent.objects.count() == 0


def test_default_retention_is_used_when_setting_is_absent(cafe, settings):
    """Regression guard for the getattr(settings, ..., DEFAULT) fallback --
    must not raise even if EVENT_RETENTION_DAYS were ever removed from
    settings."""
    del settings.EVENT_RETENTION_DAYS
    recent = make_event(cafe, occurred_at=timezone.now() - timedelta(days=5))

    deleted = prune_old_events()

    assert deleted == 0  # 5 days ago is well within the 90-day default
    assert TrackingEvent.objects.filter(pk=recent.pk).exists()
