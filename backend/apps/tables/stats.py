"""Table utilisation and turnover metrics (spec §10).

Computed on demand from `TableSession` rows, not a scheduled rollup like
apps/analytics/rollups.py -- a café has a handful of tables, not months of
individual customer visits, so there is nothing here a rollup table would
make meaningfully faster.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.cameras.models import TableZone
from apps.tables.models import TableSession
from apps.tenants.models import Cafe


def table_utilization(cafe: Cafe, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """One entry per currently-configured table (across every camera in the
    café), even one with zero sessions in range -- a table nobody sat at is
    exactly the number a café manager comparing tables wants to see, not a
    silently missing row. A table whose zone has since been deleted still
    has its history on the raw TableSession list, just not summarised here.
    """
    range_seconds = max((end - start).total_seconds(), 0.0)
    now = timezone.now()

    result: list[dict[str, Any]] = []
    for table in TableZone.objects.filter(camera__cafe=cafe).select_related("camera"):
        sessions = TableSession.objects.filter(
            cafe=cafe, table_zone_id=table.id, occupied_at__lt=end
        ).filter(Q(released_at__isnull=True) | Q(released_at__gte=start))

        occupied_seconds = 0.0
        turnover_count = 0
        for session in sessions:
            overlap_start = max(session.occupied_at, start)
            overlap_end = min(session.released_at or now, end)
            if overlap_end > overlap_start:
                occupied_seconds += (overlap_end - overlap_start).total_seconds()
            if start <= session.occupied_at < end:
                turnover_count += 1

        result.append(
            {
                "table_zone_id": str(table.id),
                "table_name": table.name,
                "camera_id": str(table.camera_id),
                "occupied_seconds": occupied_seconds,
                "turnover_count": turnover_count,
                "utilization_percent": (
                    round(occupied_seconds / range_seconds * 100, 1) if range_seconds > 0 else 0.0
                ),
            }
        )
    return result
