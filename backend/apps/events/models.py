"""Durable record of everything the AI worker reported.

This is the append-only audit log the rest of the product is derived from.
Customer sessions, table sessions and analytics snapshots (Phases 5, 9, 8) are
projections over these rows, which means a bug in a projection can be fixed by
recomputing rather than by asking a café to re-run a day.

What is stored: event type, anonymous track id, geometry, timings.
What is never stored: images, faces, embeddings, or anything naming a person.
"""
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import CafeScopedModel


class TrackingEvent(CafeScopedModel):
    """One event consumed from the AI event bus."""

    # Mirrors scv_contracts.EventType. Deliberately a plain CharField rather
    # than a constrained enum column: an older backend must be able to store an
    # event from a newer worker instead of dropping it on the floor.
    event_type = models.CharField(max_length=48, db_index=True)

    # Idempotency key. The bus is at-least-once, so redelivery is normal and
    # must not double-count an entry.
    event_id = models.UUIDField(unique=True)

    # When the worker observed it, not when we stored it. Every duration in the
    # product is computed from this column.
    occurred_at = models.DateTimeField(db_index=True)
    ingested_at = models.DateTimeField(auto_now_add=True)

    camera_id = models.UUIDField(null=True, blank=True, db_index=True)
    worker_id = models.CharField(max_length=64, blank=True, default="")

    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("tracking event")
        verbose_name_plural = _("tracking events")
        ordering = ("-occurred_at",)
        indexes = [
            models.Index(fields=["cafe", "event_type", "-occurred_at"], name="evt_cafe_type_time_idx"),
            models.Index(fields=["cafe", "camera_id", "-occurred_at"], name="evt_cafe_cam_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.occurred_at.isoformat()}"

    @property
    def ingest_lag_seconds(self) -> float | None:
        """How far behind real time the pipeline was for this event.

        The headline symptom of an overloaded café server, and the number the
        health page should surface before customers notice anything.
        """
        if not self.ingested_at:
            return None
        return (self.ingested_at - self.occurred_at).total_seconds()
