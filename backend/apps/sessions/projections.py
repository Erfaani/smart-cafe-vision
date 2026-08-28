"""Customer-session projection over the event log (spec §5).

`TrackingEvent` is the source of truth (see apps/events/models.py); this
module is what keeps `CustomerSession` in sync with it, the same way
apps/cameras/projections.py keeps `Camera` in sync. A bug here is fixed by
correcting the logic and replaying the event log, not by editing a session
by hand.

Three event types drive this:

  * `person_entered` -- opens a session, unless one is already open for this
    (camera, track_id): a person lingering near the threshold can cross it
    more than once, and a second "entry" while one is still active is jitter,
    not a second visit.
  * `person_exited` -- closes the matching open session with
    exit_reason=LINE_CROSSING. If none is open (e.g. the worker restarted
    between this person's entry and exit, so track_id no longer matches
    anything) there is nothing to close and nothing useful to record.
  * `camera_stats` -- a heartbeat. Its `active_track_ids` roster (see
    ai_worker/worker/capture.py) bumps `last_seen_at` for every open session
    still in frame, which is what lets a customer who sits still for an hour
    -- no crossings at all in that time -- stay ACTIVE instead of going stale.

Session recovery after a worker restart, and closing a session for a person
the tracker simply lost, are NOT handled here: neither produces an event at
all. Both are handled by apps.sessions.tasks.close_stale_sessions noticing
that `last_seen_at` has stopped advancing.
"""
from __future__ import annotations

import logging

from apps.events.ingest import register_projection
from apps.events.models import TrackingEvent
from apps.sessions.models import CustomerSession
from scv_contracts import Event, EventType

logger = logging.getLogger("smartcafe.sessions")


def _track_id(event: Event) -> int | None:
    value = event.payload.get("track_id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _open_session(event: Event, track_id: int) -> CustomerSession | None:
    return CustomerSession.objects.filter(
        cafe_id=event.cafe_id,
        camera_id=event.camera_id,
        track_id=track_id,
        status=CustomerSession.Status.ACTIVE,
    ).first()


def _on_person_entered(event: Event, record: TrackingEvent) -> None:
    track_id = _track_id(event)
    if track_id is None:
        return

    existing = _open_session(event, track_id)
    if existing is not None:
        existing.last_seen_at = event.occurred_at
        existing.save(update_fields=["last_seen_at", "updated_at"])
        return

    CustomerSession.objects.create(
        cafe_id=event.cafe_id,
        camera_id=event.camera_id,
        track_id=track_id,
        entry_at=event.occurred_at,
        entry_zone_name=str(event.payload.get("zone_name") or ""),
        last_seen_at=event.occurred_at,
    )


def _on_person_exited(event: Event, record: TrackingEvent) -> None:
    track_id = _track_id(event)
    if track_id is None:
        return

    session = _open_session(event, track_id)
    if session is None:
        logger.info(
            "exit_without_open_session camera=%s track_id=%s", event.camera_id, track_id
        )
        return

    session.status = CustomerSession.Status.ENDED
    session.exit_at = event.occurred_at
    session.exit_zone_name = str(event.payload.get("zone_name") or "")
    session.exit_reason = CustomerSession.ExitReason.LINE_CROSSING
    session.last_seen_at = event.occurred_at
    session.save(
        update_fields=[
            "status", "exit_at", "exit_zone_name", "exit_reason", "last_seen_at", "updated_at",
        ]
    )


def _on_camera_stats(event: Event, record: TrackingEvent) -> None:
    roster = event.payload.get("active_track_ids")
    if not isinstance(roster, list):
        return  # capture-only or detection-only mode: nothing to reconcile

    track_ids = [t for t in roster if isinstance(t, int) and not isinstance(t, bool)]
    if not track_ids:
        return

    CustomerSession.objects.filter(
        cafe_id=event.cafe_id,
        camera_id=event.camera_id,
        track_id__in=track_ids,
        status=CustomerSession.Status.ACTIVE,
    ).update(last_seen_at=event.occurred_at)


register_projection(EventType.PERSON_ENTERED, _on_person_entered)
register_projection(EventType.PERSON_EXITED, _on_person_exited)
register_projection(EventType.CAMERA_STATS, _on_camera_stats)
