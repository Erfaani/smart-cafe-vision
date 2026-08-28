"""Computes one café's DailyStat row for one local calendar day.

The only place that reads raw CustomerSession rows for analytics purposes --
everything else (the API, the dashboard) reads DailyStat instead, which is
what keeps a year of history from meaning a slow query. Called by
apps.analytics.tasks (the scheduled path) and by the backfill_daily_stats
management command (the one-time historical path); both converge here so
behaviour cannot drift between them.
"""
from __future__ import annotations

import zoneinfo
from datetime import date as date_type
from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.analytics.models import DailyStat
from apps.sessions.models import CustomerSession
from apps.tenants.models import Cafe


def compute_daily_stat(cafe: Cafe, date: date_type) -> DailyStat:
    """Upserts and returns the DailyStat for `date` in `cafe`'s own
    timezone. Safe to call repeatedly -- a day that is still in progress is
    simply recomputed from scratch each time, not accumulated onto."""
    tz = zoneinfo.ZoneInfo(cafe.timezone)
    day_start = datetime.combine(date, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    now = timezone.now()

    sessions = CustomerSession.objects.filter(cafe=cafe, entry_at__gte=day_start, entry_at__lt=day_end)
    rows = list(sessions.values("entry_at", "exit_at", "status"))

    ended_durations = [
        (row["exit_at"] - row["entry_at"]).total_seconds()
        for row in rows
        if row["status"] == CustomerSession.Status.ENDED and row["exit_at"] is not None
    ]
    total_stay_seconds = sum(ended_durations)

    hourly_entries = [0] * 24
    for row in rows:
        hourly_entries[row["entry_at"].astimezone(tz).hour] += 1

    peak_occupancy, peak_occupancy_at = _peak_concurrent(
        [(row["entry_at"], row["exit_at"] or now) for row in rows]
    )

    stat, _created = DailyStat.objects.update_or_create(
        cafe=cafe,
        date=date,
        defaults={
            "visitor_count": len(rows),
            "ended_session_count": len(ended_durations),
            "total_stay_seconds": total_stay_seconds,
            "average_stay_seconds": (
                total_stay_seconds / len(ended_durations) if ended_durations else None
            ),
            "longest_stay_seconds": max(ended_durations) if ended_durations else None,
            "hourly_entries": hourly_entries,
            "peak_occupancy": peak_occupancy,
            "peak_occupancy_at": peak_occupancy_at,
            "is_final": day_end <= now,
        },
    )
    return stat


def _peak_concurrent(
    intervals: list[tuple[datetime, datetime]],
) -> tuple[int, datetime | None]:
    """Max simultaneous occupancy across a set of [start, end) intervals, via
    a standard sweep -- O(n log n), n bounded by one café's daily visit
    count, never large enough to matter.

    At an exact tie between one person's exit and another's entry, the exit
    is processed first (so a same-instant handoff never inflates the peak by
    one) -- deliberately conservative, and astronomically rare with real
    timestamps regardless.
    """
    events: list[tuple[datetime, int]] = []
    for start, end in intervals:
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda event: (event[0], event[1]))  # -1 before +1 at an exact tie

    count = 0
    peak = 0
    peak_at: datetime | None = None
    for at, delta in events:
        count += delta
        if count > peak:
            peak = count
            peak_at = at
    return peak, peak_at
