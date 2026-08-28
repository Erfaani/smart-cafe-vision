"""Celery housekeeping: prune the raw event log past its retention window.

`TrackingEvent` is deliberately kept prunable, not permanent (see its own
module docstring): every durable figure the product reports -- customer
sessions, table sessions, daily analytics rollups (Phases 5, 9, 8) -- is a
projection computed from these rows at ingest time and stored in its own
table, so deleting an old `TrackingEvent` row does not lose anything the
dashboard, analytics, or a café's historical reporting still shows. What is
lost is only the ability to *recompute* a projection for that day if a bug
is ever found in one -- the trade this retention window makes deliberately,
in exchange for not growing an append-only table forever on a café's mini
PC (spec §16, docs/privacy.md's Retention section).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.events.models import TrackingEvent

logger = logging.getLogger("smartcafe.events")

DEFAULT_RETENTION_DAYS = 90


@shared_task(name="apps.events.prune_old_events")
def prune_old_events() -> int:
    """Deletes every TrackingEvent older than EVENT_RETENTION_DAYS.

    A retention of 0 (or less) disables pruning -- an explicit, readable
    opt-out for an operator who wants to keep the full raw log, rather than
    a magic sentinel buried in the task body.
    """
    retention_days = getattr(settings, "EVENT_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)
    if retention_days <= 0:
        return 0

    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted, _ = TrackingEvent.objects.filter(occurred_at__lt=cutoff).delete()

    if deleted:
        logger.info("old_events_pruned count=%s retention_days=%s", deleted, retention_days)
    return deleted
