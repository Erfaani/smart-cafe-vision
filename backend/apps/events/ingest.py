"""Turning bus events into database rows.

One function, `ingest`, is the only path from the event bus into the database.
Phases 3–9 register additional projections through `register_projection` rather
than adding branches here, so the ingest path itself stays small enough to
reason about while the pipeline is running live.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from apps.events.models import TrackingEvent
from apps.tenants.models import Cafe
from scv_contracts import Event, EventType

logger = logging.getLogger("smartcafe.events")

Projection = Callable[[Event, TrackingEvent], None]
_projections: dict[str, list[Projection]] = defaultdict(list)


def register_projection(event_type: EventType | str, handler: Projection) -> None:
    """Register a side effect for one event type.

    Projections run inside the ingest transaction: if one raises, the event is
    not acknowledged and will be redelivered.
    """
    _projections[str(event_type)].append(handler)


def _coerce_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


class IngestResult:
    __slots__ = ("stored", "duplicate", "rejected", "reason", "record")

    def __init__(
        self,
        *,
        stored: bool = False,
        duplicate: bool = False,
        rejected: bool = False,
        reason: str = "",
        record: TrackingEvent | None = None,
    ) -> None:
        self.stored = stored
        self.duplicate = duplicate
        self.rejected = rejected
        self.reason = reason
        self.record = record

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "stored" if self.stored else "duplicate" if self.duplicate else "rejected"
        return f"<IngestResult {state} {self.reason}>"


def ingest(event: Event) -> IngestResult:
    """Persist one event exactly once and run its projections."""
    cafe_pk = _coerce_uuid(event.cafe_id)
    if cafe_pk is None:
        return IngestResult(rejected=True, reason="cafe_id is not a valid UUID")

    if not Cafe.objects.filter(pk=cafe_pk).exists():
        # An event for an unknown café is dropped, not stored: it usually means
        # a worker still configured for a café that was removed.
        logger.warning("event_unknown_cafe cafe=%s type=%s", event.cafe_id, event.type)
        return IngestResult(rejected=True, reason="unknown cafe")

    event_pk = _coerce_uuid(event.event_id)
    if event_pk is None:
        return IngestResult(rejected=True, reason="event_id is not a valid UUID")

    try:
        with transaction.atomic():
            record = TrackingEvent.objects.create(
                cafe_id=cafe_pk,
                event_id=event_pk,
                event_type=str(event.type),
                occurred_at=event.occurred_at,
                camera_id=_coerce_uuid(event.camera_id),
                worker_id=(event.worker_id or "")[:64],
                payload=event.payload,
            )
            for handler in _projections.get(str(event.type), ()):
                handler(event, record)
    except IntegrityError:
        # Redelivery after a consumer restart. Expected, not an error.
        logger.debug("event_duplicate id=%s type=%s", event.event_id, event.type)
        return IngestResult(duplicate=True, reason="already ingested")

    return IngestResult(stored=True, record=record)


def ingest_many(events: list[Event]) -> dict[str, int]:
    """Ingest a batch, reporting a per-outcome tally."""
    tally = {"stored": 0, "duplicate": 0, "rejected": 0}
    for event in events:
        result = ingest(event)
        if result.stored:
            tally["stored"] += 1
        elif result.duplicate:
            tally["duplicate"] += 1
        else:
            tally["rejected"] += 1
    return tally
