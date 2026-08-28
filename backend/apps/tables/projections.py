"""Table-session projection over the event log (spec §10).

Mirrors apps/sessions/projections.py's structure closely -- read that
module's docstring first. Three event types drive this the same way:

  * `table_occupied` -- opens a session, unless one is already open for this
    (camera, table_zone_id), in which case it is treated as a heartbeat
    (bumps last_seen_at) rather than a second session. Under normal
    operation this should never actually happen -- the worker's own debounce
    (ai_worker/worker/tables.py) only fires once per state transition -- but
    treating a duplicate as a heartbeat rather than trusting that invariant
    blindly costs nothing and avoids a spurious extra session if it is ever
    violated.
  * `table_released` -- closes the matching open session with
    release_reason=CLEARED. If none is open there is nothing to close.
  * `camera_stats` -- its `occupied_table_ids` roster (see
    ai_worker/worker/capture.py) bumps last_seen_at for every table still
    confirmed occupied, which is what lets a long-occupied table stay
    correctly ACTIVE between discrete occupied/released events.

Closing a table session whose worker went quiet without a clean release is
NOT handled here -- neither event exists to react to. See
apps.tables.tasks.close_stale_table_sessions.
"""
from __future__ import annotations

import logging

from apps.events.ingest import register_projection
from apps.events.models import TrackingEvent
from apps.tables.models import TableSession
from scv_contracts import Event, EventType

logger = logging.getLogger("smartcafe.tables")


def _open_session(event: Event, table_id: str) -> TableSession | None:
    return TableSession.objects.filter(
        cafe_id=event.cafe_id,
        camera_id=event.camera_id,
        table_zone_id=table_id,
        status=TableSession.Status.ACTIVE,
    ).first()


def _on_table_occupied(event: Event, record: TrackingEvent) -> None:
    table_id = event.payload.get("table_id")
    if not table_id:
        return

    existing = _open_session(event, table_id)
    if existing is not None:
        existing.last_seen_at = event.occurred_at
        existing.save(update_fields=["last_seen_at", "updated_at"])
        return

    TableSession.objects.create(
        cafe_id=event.cafe_id,
        camera_id=event.camera_id,
        table_zone_id=table_id,
        table_name=str(event.payload.get("table_name") or ""),
        occupied_at=event.occurred_at,
        last_seen_at=event.occurred_at,
    )


def _on_table_released(event: Event, record: TrackingEvent) -> None:
    table_id = event.payload.get("table_id")
    if not table_id:
        return

    session = _open_session(event, table_id)
    if session is None:
        logger.info(
            "table_released_without_open_session camera=%s table=%s", event.camera_id, table_id
        )
        return

    session.status = TableSession.Status.ENDED
    session.released_at = event.occurred_at
    session.release_reason = TableSession.ReleaseReason.CLEARED
    session.last_seen_at = event.occurred_at
    session.save(
        update_fields=["status", "released_at", "release_reason", "last_seen_at", "updated_at"]
    )


def _on_camera_stats(event: Event, record: TrackingEvent) -> None:
    roster = event.payload.get("occupied_table_ids")
    if not isinstance(roster, list):
        return  # no table detector configured for this camera

    table_ids = [str(t) for t in roster if t]
    if not table_ids:
        return

    TableSession.objects.filter(
        cafe_id=event.cafe_id,
        camera_id=event.camera_id,
        table_zone_id__in=table_ids,
        status=TableSession.Status.ACTIVE,
    ).update(last_seen_at=event.occurred_at)


register_projection(EventType.TABLE_OCCUPIED, _on_table_occupied)
register_projection(EventType.TABLE_RELEASED, _on_table_released)
register_projection(EventType.CAMERA_STATS, _on_camera_stats)
