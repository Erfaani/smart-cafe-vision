"""DailyStat: the one rollup table Phase 8 needs (spec: "scheduled rollups so
a year of history does not mean a slow query").

One row per café per local calendar day. A year of daily rows is ~365 per
café -- trivially fast to scan and aggregate client-side for any range a
dashboard would ask for, so there is no second rollup granularity (weekly,
monthly) here: a "monthly trend" is just a wider date range over this same
table, not a separately maintained aggregate.

Computed by `apps.analytics.rollups.compute_daily_stat`, never written to
directly -- a projection over `CustomerSession`, same principle as every
other derived table in this product (apps/cameras/models.py's
`Camera.connection_status` and friends, apps/sessions/models.py's whole
existence). A bug here is fixed by correcting the rollup function and
recomputing, not by editing a row by hand.
"""
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import CafeScopedModel


class DailyStat(CafeScopedModel):
    date = models.DateField(db_index=True)

    # Every session whose entry_at falls on this local day -- active or
    # ended. The denominator for a correctly-weighted multi-day average is
    # `ended_session_count`, not this: a still-open session has no final
    # duration to contribute yet.
    visitor_count = models.PositiveIntegerField(default=0)

    ended_session_count = models.PositiveIntegerField(default=0)
    total_stay_seconds = models.FloatField(default=0.0)
    average_stay_seconds = models.FloatField(null=True, blank=True)
    longest_stay_seconds = models.FloatField(null=True, blank=True)

    # Entries bucketed by local hour-of-day (index 0-23) -- "when do people
    # arrive", the basis for a peak-hours chart. Deliberately entry-based,
    # not a reconstruction of who was present at each hour: a café's "busy
    # hour" is a defensible, simple thing to ask for, and the alternative
    # (occupancy at every hour boundary) still would not answer the same
    # question a genuine peak-*concurrency* moment does -- see
    # peak_occupancy below for that instead.
    hourly_entries = models.JSONField(default=list)

    # True concurrent-occupancy peak for the day, from a sweep over every
    # session's [entry_at, exit_at) interval -- not the same number as "the
    # hour with the most arrivals" above, and can genuinely differ (a
    # handful of long stays overlapping outlasts a short morning rush).
    peak_occupancy = models.PositiveIntegerField(default=0)
    peak_occupancy_at = models.DateTimeField(null=True, blank=True)

    # False until the local day is fully over -- apps.analytics.tasks
    # recomputes a non-final row on every run (today's numbers are always
    # partial) and stops recomputing once true, so a finished day's rollup
    # is not needlessly rescanned forever.
    is_final = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("daily stat")
        verbose_name_plural = _("daily stats")
        ordering = ("-date",)
        constraints = [
            models.UniqueConstraint(fields=["cafe", "date"], name="unique_daily_stat_per_cafe_day"),
        ]
        indexes = [
            models.Index(fields=["cafe", "-date"], name="dailystat_cafe_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.cafe_id} {self.date}"
