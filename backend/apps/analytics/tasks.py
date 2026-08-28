"""Celery housekeeping: keeps DailyStat current.

Runs every ANALYTICS_ROLLUP_INTERVAL_SECONDS and recomputes, for every active
café, in that café's own timezone: today (always -- a day in progress is
never final) and yesterday, but only if its row is missing or was not yet
marked final -- a safety net for a beat cycle that landed right at local
midnight and finalised "today" a tick before the date actually rolled over
elsewhere.

This does not backfill history: a café that already had months of sessions
before Phase 8 shipped needs `manage.py backfill_daily_stats` once, run by a
technician during upgrade -- see that command's own docstring.
"""
from __future__ import annotations

import logging
import zoneinfo
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.analytics.models import DailyStat
from apps.analytics.rollups import compute_daily_stat
from apps.tenants.models import Cafe

logger = logging.getLogger("smartcafe.analytics")


@shared_task(name="apps.analytics.refresh_daily_stats")
def refresh_daily_stats() -> int:
    """Returns how many DailyStat rows were recomputed."""
    count = 0
    for cafe in Cafe.objects.filter(is_active=True):
        tz = zoneinfo.ZoneInfo(cafe.timezone)
        today = timezone.now().astimezone(tz).date()
        yesterday = today - timedelta(days=1)

        compute_daily_stat(cafe, today)
        count += 1

        stat = DailyStat.objects.filter(cafe=cafe, date=yesterday).first()
        if stat is None or not stat.is_final:
            compute_daily_stat(cafe, yesterday)
            count += 1

    logger.info("daily_stats_refreshed rows=%s", count)
    return count
