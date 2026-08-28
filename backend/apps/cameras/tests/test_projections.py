"""The projections in apps/cameras/projections.py are registered once, at app
startup (CamerasConfig.ready()) -- these tests exercise the real, permanently
registered handlers by ingesting real events, rather than registering their
own throwaway ones.
"""
from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from apps.cameras.models import Camera
from apps.events.ingest import ingest
from scv_contracts import Event, EventType

pytestmark = pytest.mark.django_db


def make_camera(cafe, **overrides) -> Camera:
    defaults = {"cafe": cafe, "name": "Entrance", "rtsp_url": "rtsp://192.168.1.64:554/live"}
    defaults.update(overrides)
    return Camera.objects.create(**defaults)


def test_camera_connected_event_marks_the_camera_connected(cafe):
    camera = make_camera(cafe, connection_status=Camera.ConnectionStatus.ERROR, last_error="boom")

    ingest(Event(type=EventType.CAMERA_CONNECTED, cafe_id=str(cafe.id), camera_id=str(camera.id)))

    camera.refresh_from_db()
    assert camera.connection_status == Camera.ConnectionStatus.CONNECTED
    assert camera.last_error == ""
    assert camera.last_connected_at is not None


def test_camera_disconnected_event_records_the_reason(cafe):
    camera = make_camera(cafe, connection_status=Camera.ConnectionStatus.CONNECTED)

    ingest(
        Event(
            type=EventType.CAMERA_DISCONNECTED,
            cafe_id=str(cafe.id),
            camera_id=str(camera.id),
            payload={"reason": "stream_timeout"},
        )
    )

    camera.refresh_from_db()
    assert camera.connection_status == Camera.ConnectionStatus.ERROR
    assert camera.last_error == "stream_timeout"


def test_camera_stats_event_updates_fps_and_resolution(cafe):
    camera = make_camera(cafe)

    ingest(
        Event(
            type=EventType.CAMERA_STATS,
            cafe_id=str(cafe.id),
            camera_id=str(camera.id),
            payload={"fps": 8.5, "width": 1920, "height": 1080},
        )
    )

    camera.refresh_from_db()
    assert camera.last_fps == 8.5
    assert (camera.resolution_width, camera.resolution_height) == (1920, 1080)
    assert camera.last_frame_at is not None


def test_camera_stats_event_without_frame_timestamp_falls_back_to_occurred_at(cafe):
    camera = make_camera(cafe)
    occurred_at = timezone.now()

    ingest(
        Event(
            type=EventType.CAMERA_STATS,
            cafe_id=str(cafe.id),
            camera_id=str(camera.id),
            occurred_at=occurred_at,
            payload={"fps": 5.0},
        )
    )

    camera.refresh_from_db()
    assert abs((camera.last_frame_at - occurred_at).total_seconds()) < 0.001


def test_camera_stats_event_records_the_latest_detection(cafe):
    camera = make_camera(cafe)

    ingest(
        Event(
            type=EventType.CAMERA_STATS,
            cafe_id=str(cafe.id),
            camera_id=str(camera.id),
            payload={"fps": 8.5, "person_count": 3, "inference_ms": 42.7},
        )
    )

    camera.refresh_from_db()
    assert camera.last_person_count == 3
    assert camera.last_inference_ms == pytest.approx(42.7)


def test_camera_stats_event_without_detection_fields_leaves_them_untouched(cafe):
    """Capture-only mode: the worker never sends person_count/inference_ms at
    all, and a previously recorded value must not be silently reset."""
    camera = make_camera(cafe, last_person_count=5, last_inference_ms=10.0)

    ingest(
        Event(
            type=EventType.CAMERA_STATS,
            cafe_id=str(cafe.id),
            camera_id=str(camera.id),
            payload={"fps": 8.5},
        )
    )

    camera.refresh_from_db()
    assert camera.last_person_count == 5
    assert camera.last_inference_ms == 10.0


def test_camera_stats_event_with_zero_people_is_recorded_not_ignored(cafe):
    """0 is a meaningful, falsy value -- must not be treated the same as
    'field absent'."""
    camera = make_camera(cafe, last_person_count=5)

    ingest(
        Event(
            type=EventType.CAMERA_STATS,
            cafe_id=str(cafe.id),
            camera_id=str(camera.id),
            payload={"fps": 8.5, "person_count": 0, "inference_ms": 15.0},
        )
    )

    camera.refresh_from_db()
    assert camera.last_person_count == 0


def test_camera_stats_event_records_the_latest_track_count(cafe):
    camera = make_camera(cafe)

    ingest(
        Event(
            type=EventType.CAMERA_STATS,
            cafe_id=str(cafe.id),
            camera_id=str(camera.id),
            payload={"fps": 8.5, "person_count": 3, "inference_ms": 42.7, "track_count": 2},
        )
    )

    camera.refresh_from_db()
    # The two figures are recorded independently and may legitimately differ
    # (a briefly-occluded person the tracker still counts, that this instant's
    # raw detector output does not) -- see Camera.last_track_count.
    assert camera.last_person_count == 3
    assert camera.last_track_count == 2


def test_camera_stats_event_without_track_count_leaves_it_untouched(cafe):
    """Detection without tracking (a tracker that failed to build) must not
    silently reset a previously recorded track count."""
    camera = make_camera(cafe, last_track_count=4)

    ingest(
        Event(
            type=EventType.CAMERA_STATS,
            cafe_id=str(cafe.id),
            camera_id=str(camera.id),
            payload={"fps": 8.5, "person_count": 3, "inference_ms": 42.7},
        )
    )

    camera.refresh_from_db()
    assert camera.last_track_count == 4


def test_camera_stats_event_with_zero_tracks_is_recorded_not_ignored(cafe):
    camera = make_camera(cafe, last_track_count=5)

    ingest(
        Event(
            type=EventType.CAMERA_STATS,
            cafe_id=str(cafe.id),
            camera_id=str(camera.id),
            payload={"fps": 8.5, "track_count": 0},
        )
    )

    camera.refresh_from_db()
    assert camera.last_track_count == 0


def test_event_for_a_deleted_camera_does_not_raise(cafe):
    """A camera can be removed from the dashboard after the worker already
    picked it up; a late event for it must not crash the consumer."""
    missing_camera_id = str(uuid.uuid4())

    result = ingest(
        Event(type=EventType.CAMERA_CONNECTED, cafe_id=str(cafe.id), camera_id=missing_camera_id)
    )

    assert result.stored  # the raw event is still recorded; only the projection is a no-op


def test_projection_only_touches_the_camera_in_its_own_cafe(cafe, other_cafe):
    """An event carrying a camera id that belongs to a different café than the
    event's own cafe_id must not be able to update it."""
    foreign_camera = make_camera(other_cafe, connection_status=Camera.ConnectionStatus.UNKNOWN)

    ingest(
        Event(type=EventType.CAMERA_CONNECTED, cafe_id=str(cafe.id), camera_id=str(foreign_camera.id))
    )

    foreign_camera.refresh_from_db()
    assert foreign_camera.connection_status == Camera.ConnectionStatus.UNKNOWN
