"""Camera-status projection over the event log.

`TrackingEvent` is the source of truth (see apps/events/models.py); this module
is what keeps `Camera.connection_status` etc. in sync with it. If this logic
ever has a bug, the fix is to correct it and replay the event log -- not to ask
a café to fix the row by hand.
"""
from __future__ import annotations

import logging

from django.utils.dateparse import parse_datetime

from apps.cameras.models import Camera
from apps.events.ingest import register_projection
from apps.events.models import TrackingEvent
from scv_contracts import Event, EventType

logger = logging.getLogger("smartcafe.cameras")


def _get_camera(event: Event) -> Camera | None:
    if not event.camera_id:
        return None
    try:
        return Camera.objects.get(pk=event.camera_id, cafe_id=event.cafe_id)
    except (Camera.DoesNotExist, ValueError):
        # A camera can be deleted from the dashboard after the worker already
        # picked it up; a late-arriving event for it is not an error.
        logger.info("camera_event_for_unknown_camera camera=%s", event.camera_id)
        return None


def _on_camera_connected(event: Event, record: TrackingEvent) -> None:
    camera = _get_camera(event)
    if camera is None:
        return
    camera.connection_status = Camera.ConnectionStatus.CONNECTED
    camera.last_connected_at = event.occurred_at
    camera.last_error = ""
    camera.save(update_fields=["connection_status", "last_connected_at", "last_error", "updated_at"])


def _on_camera_disconnected(event: Event, record: TrackingEvent) -> None:
    camera = _get_camera(event)
    if camera is None:
        return
    camera.connection_status = Camera.ConnectionStatus.ERROR
    camera.last_error = str(event.payload.get("error") or event.payload.get("reason") or "")[:255]
    camera.save(update_fields=["connection_status", "last_error", "updated_at"])


def _on_camera_stats(event: Event, record: TrackingEvent) -> None:
    camera = _get_camera(event)
    if camera is None:
        return

    payload = event.payload
    fields: list[str] = []

    fps = payload.get("fps")
    if isinstance(fps, (int, float)):
        camera.last_fps = float(fps)
        fields.append("last_fps")

    width, height = payload.get("width"), payload.get("height")
    if isinstance(width, int) and isinstance(height, int):
        camera.resolution_width = width
        camera.resolution_height = height
        fields.extend(["resolution_width", "resolution_height"])

    last_frame_at = payload.get("last_frame_at")
    if isinstance(last_frame_at, str) and (parsed := parse_datetime(last_frame_at)):
        camera.last_frame_at = parsed
        fields.append("last_frame_at")
    else:
        camera.last_frame_at = event.occurred_at
        fields.append("last_frame_at")

    # Phase 3: present only when the worker actually ran a detection tick
    # before this stats event -- absent entirely in capture-only mode (no
    # detector loaded), so these two fields simply stay whatever they were.
    person_count = payload.get("person_count")
    if isinstance(person_count, int) and not isinstance(person_count, bool):
        camera.last_person_count = person_count
        fields.append("last_person_count")

    inference_ms = payload.get("inference_ms")
    if isinstance(inference_ms, (int, float)) and not isinstance(inference_ms, bool):
        camera.last_inference_ms = float(inference_ms)
        fields.append("last_inference_ms")

    # Phase 4: present only when a tracker actually ran alongside detection.
    # Deliberately a separate column from last_person_count -- see the field's
    # own docstring in apps/cameras/models.py for why they can legitimately
    # differ.
    track_count = payload.get("track_count")
    if isinstance(track_count, int) and not isinstance(track_count, bool):
        camera.last_track_count = track_count
        fields.append("last_track_count")

    if fields:
        camera.save(update_fields=[*fields, "updated_at"])


register_projection(EventType.CAMERA_CONNECTED, _on_camera_connected)
register_projection(EventType.CAMERA_DISCONNECTED, _on_camera_disconnected)
register_projection(EventType.CAMERA_STATS, _on_camera_stats)
