"""Celery housekeeping: close sessions abandoned by a lost or restarted tracker.

Two situations never produce a person_exited event and would otherwise leave
a CustomerSession ACTIVE forever, corrupting every occupancy count and
stay-time average computed from it:

  * the tracker genuinely loses the person (an occlusion longer than
    ZoneCrossingDetector's own tolerance, a camera glitch) without them ever
    crossing an exit line;
  * the AI worker process restarts. Its tracker's track ids start over from
    zero (see ai_worker/worker/tracker.py), so no future event -- crossing or
    heartbeat -- will ever again reference the old session's track_id.

Both look identical from here: an ACTIVE session whose last_seen_at has
simply stopped advancing. This task is what notices and closes it.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.sessions.models import CustomerSession

logger = logging.getLogger("smartcafe.sessions")

DEFAULT_STALE_GRACE_SECONDS = 120


@shared_task(name="apps.sessions.close_stale_sessions")
def close_stale_sessions() -> int:
    """Ends every ACTIVE session whose last_seen_at is older than the grace
    period, returning how many were closed.

    `exit_at` is set to the session's own `last_seen_at`, not "now" -- the
    best available estimate of when the person actually left, so a slow beat
    schedule or a delayed run never inflates a customer's measured stay.
    """
    grace_seconds = getattr(settings, "SESSION_STALE_GRACE_SECONDS", DEFAULT_STALE_GRACE_SECONDS)
    cutoff = timezone.now() - timedelta(seconds=grace_seconds)

    stale = CustomerSession.objects.filter(
        status=CustomerSession.Status.ACTIVE, last_seen_at__lt=cutoff
    )

    count = 0
    for session in stale.iterator():
        session.status = CustomerSession.Status.ENDED
        session.exit_at = session.last_seen_at
        session.exit_reason = CustomerSession.ExitReason.TRACK_LOST
        session.save(update_fields=["status", "exit_at", "exit_reason", "updated_at"])
        count += 1

    if count:
        logger.info("stale_sessions_closed count=%s grace_seconds=%s", count, grace_seconds)
    return count
