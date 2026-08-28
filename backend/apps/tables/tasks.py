"""Celery housekeeping: closes table sessions whose worker went quiet.

Mirrors apps/sessions/tasks.py exactly -- same failure this exists to catch
(no table_released event ever arrives if the AI worker crashes, or a camera
disconnects, mid-occupancy), same fix (a grace period against last_seen_at,
kept current by the camera_stats occupied_table_ids heartbeat).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.tables.models import TableSession

logger = logging.getLogger("smartcafe.tables")

DEFAULT_STALE_GRACE_SECONDS = 120


@shared_task(name="apps.tables.close_stale_table_sessions")
def close_stale_table_sessions() -> int:
    """Ends every ACTIVE table session whose last_seen_at is older than the
    grace period, returning how many were closed. `released_at` is set to
    the session's own `last_seen_at`, not "now" -- the best estimate of when
    the table actually cleared."""
    grace_seconds = getattr(settings, "TABLE_STALE_GRACE_SECONDS", DEFAULT_STALE_GRACE_SECONDS)
    cutoff = timezone.now() - timedelta(seconds=grace_seconds)

    stale = TableSession.objects.filter(
        status=TableSession.Status.ACTIVE, last_seen_at__lt=cutoff
    )

    count = 0
    for session in stale.iterator():
        session.status = TableSession.Status.ENDED
        session.released_at = session.last_seen_at
        session.release_reason = TableSession.ReleaseReason.STALE
        session.save(update_fields=["status", "released_at", "release_reason", "updated_at"])
        count += 1

    if count:
        logger.info("stale_table_sessions_closed count=%s grace_seconds=%s", count, grace_seconds)
    return count
