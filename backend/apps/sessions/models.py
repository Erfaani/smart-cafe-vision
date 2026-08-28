"""CustomerSession model (spec §5).

A projection over the event log, not independent data: every field here is
derived from person_entered / person_exited crossings and camera_stats
heartbeats (see apps/sessions/projections.py), and could in principle be
recomputed from scratch by replaying TrackingEvent -- same principle as
apps/cameras/models.py's Camera.connection_status and friends.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.color import color_for_duration
from apps.core.models import CafeScopedModel


class CustomerSession(CafeScopedModel):
    """One customer's presence in a camera's frame, entry to exit.

    `camera_id` is a plain UUID, not a ForeignKey -- deliberately mirroring
    `apps.events.models.TrackingEvent`. A session is a historical analytics
    record and must survive the camera that produced it being edited or
    deleted, the same way an old audit-log entry outlives the system that
    wrote it.

    `track_id` is only unique within one camera's current AI worker process
    -- not globally, and not across a worker restart (see
    ai_worker/worker/tracker.py's module docstring). It is meaningful here
    only as a short-lived key used to match a later exit crossing, or a
    camera_stats heartbeat, back to the session an entry crossing opened
    moments or hours earlier.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        ENDED = "ended", _("Ended")

    class ExitReason(models.TextChoices):
        LINE_CROSSING = "line_crossing", _("Crossed an exit line")
        TRACK_LOST = "track_lost", _("Tracker lost the person")

    camera_id = models.UUIDField(db_index=True)
    track_id = models.PositiveIntegerField()

    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )

    entry_at = models.DateTimeField()
    entry_zone_name = models.CharField(max_length=120, blank=True, default="")

    exit_at = models.DateTimeField(null=True, blank=True)
    exit_zone_name = models.CharField(max_length=120, blank=True, default="")
    exit_reason = models.CharField(max_length=16, choices=ExitReason.choices, blank=True, default="")

    # Most recent evidence this track was still present: a crossing event, or
    # a camera_stats heartbeat naming this track_id in its active roster (see
    # ai_worker/worker/capture.py's active_track_ids payload field). Drives
    # apps.sessions.tasks.close_stale_sessions -- an internal housekeeping
    # field, not meant to be shown to staff directly.
    last_seen_at = models.DateTimeField()

    class Meta:
        verbose_name = _("customer session")
        verbose_name_plural = _("customer sessions")
        ordering = ("-entry_at",)
        indexes = [
            models.Index(fields=["cafe", "status", "-entry_at"], name="sess_cafe_status_entry_idx"),
            models.Index(fields=["camera_id", "track_id", "status"], name="sess_camera_track_status_idx"),
        ]

    def __str__(self) -> str:
        return f"track {self.track_id} on camera {self.camera_id} ({self.status})"

    @property
    def duration_seconds(self) -> float:
        """Stay time from real timestamps (spec §5), never frame counts.

        For a still-ACTIVE session this is "duration so far, as of now" -- a
        snapshot at read time, not a live value. The dashboard's live counter
        (Phase 5 frontend) ticks independently from `entry_at` between
        requests; this field is for anything that only reads the API once,
        such as an analytics export.
        """
        end = self.exit_at or timezone.now()
        return (end - self.entry_at).total_seconds()

    @property
    def color(self) -> str:
        """Same rule, same snapshot caveat as `duration_seconds` above --
        computed from `self.cafe.stay_color_stops` (Phase 6) via
        `apps.core.color.color_for_duration`, the single implementation
        shared with the public display and the dashboard's own live-ticking
        colour (frontend/src/lib/stay-color.ts is its exact mirror, not a
        second Python-independent version)."""
        return color_for_duration(self.duration_seconds, self.cafe.stay_color_stops)
