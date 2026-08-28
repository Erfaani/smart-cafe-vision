"""TableSession model (spec §10).

A projection over the event log, not independent data -- every field here is
derived from table_occupied / table_released crossings and camera_stats
heartbeats (see apps/tables/projections.py), the exact same relationship
apps.sessions.models.CustomerSession has to person_entered / person_exited.
Read that model's docstring first; this one only calls out where a table
genuinely differs from a customer.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import CafeScopedModel


class TableSession(CafeScopedModel):
    """One continuous stretch of a table being occupied.

    `camera_id` and `table_zone_id` are plain UUIDs, not ForeignKeys --
    mirroring CustomerSession's own `camera_id` exactly, for the same
    reason: a session is a historical analytics record and must survive the
    camera or the table zone that produced it being edited or deleted.
    `table_name` is a denormalised snapshot taken at `occupied_at`, so a
    later rename (or deletion) of the table never rewrites history.

    Unlike a customer, a table has no "track id" to reuse across separate
    visits -- `table_zone_id` alone identifies which table a session belongs
    to, and the projection (apps/tables/projections.py) only ever has at
    most one ACTIVE session per table_zone_id at a time, by construction: a
    second table_occupied for an already-open session is treated as a
    heartbeat, never a second session.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        ENDED = "ended", _("Ended")

    class ReleaseReason(models.TextChoices):
        CLEARED = "cleared", _("Occupancy cleared")
        STALE = "stale", _("Worker went quiet")

    camera_id = models.UUIDField(db_index=True)
    table_zone_id = models.UUIDField(db_index=True)
    table_name = models.CharField(max_length=120)

    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )

    occupied_at = models.DateTimeField()
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.CharField(max_length=16, choices=ReleaseReason.choices, blank=True, default="")

    # Most recent evidence this table was still occupied: a table_occupied
    # heartbeat, or a camera_stats occupied_table_ids roster naming this
    # table_zone_id (see ai_worker/worker/capture.py). Drives
    # apps.tables.tasks.close_stale_table_sessions -- internal housekeeping,
    # same role as CustomerSession.last_seen_at.
    last_seen_at = models.DateTimeField()

    class Meta:
        verbose_name = _("table session")
        verbose_name_plural = _("table sessions")
        ordering = ("-occupied_at",)
        indexes = [
            models.Index(fields=["cafe", "status", "-occupied_at"], name="tablesess_cafe_status_idx"),
            models.Index(fields=["table_zone_id", "status"], name="tablesess_table_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.table_name} on camera {self.camera_id} ({self.status})"

    @property
    def duration_seconds(self) -> float:
        """Same snapshot caveat as CustomerSession.duration_seconds: for a
        still-ACTIVE session this is "duration so far, as of now", not a
        live value."""
        end = self.released_at or timezone.now()
        return (end - self.occupied_at).total_seconds()
