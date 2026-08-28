"""The projections in apps/sessions/projections.py are registered once, at app
startup (SessionsConfig.ready()) -- these tests exercise the real, permanently
registered handlers by ingesting real events, rather than registering their
own throwaway ones. Same approach as apps/cameras/tests/test_projections.py.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.events.ingest import ingest
from apps.sessions.models import CustomerSession
from scv_contracts import Event, EventType

pytestmark = pytest.mark.django_db


def camera_id() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# person_entered
# --------------------------------------------------------------------------- #
def test_person_entered_opens_a_new_session(cafe):
    cam = camera_id()
    occurred_at = timezone.now()

    ingest(
        Event(
            type=EventType.PERSON_ENTERED,
            cafe_id=str(cafe.id),
            camera_id=cam,
            occurred_at=occurred_at,
            payload={"track_id": 3, "zone_id": "z1", "zone_name": "Front door", "x": 1.0, "y": 2.0},
        )
    )

    session = CustomerSession.objects.get(camera_id=cam, track_id=3)
    assert session.status == CustomerSession.Status.ACTIVE
    assert session.entry_zone_name == "Front door"
    assert abs((session.entry_at - occurred_at).total_seconds()) < 0.001
    assert abs((session.last_seen_at - occurred_at).total_seconds()) < 0.001
    assert session.exit_at is None


def test_a_second_entry_for_an_already_open_session_is_treated_as_a_heartbeat(cafe):
    """A person lingering near the threshold can cross it more than once; a
    second 'entry' while one is already open must not create a duplicate
    session or reset entry_at."""
    cam = camera_id()
    first_entry = timezone.now()
    ingest(
        Event(
            type=EventType.PERSON_ENTERED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=first_entry, payload={"track_id": 3},
        )
    )
    later = first_entry + timedelta(seconds=5)
    ingest(
        Event(
            type=EventType.PERSON_ENTERED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=later, payload={"track_id": 3},
        )
    )

    assert CustomerSession.objects.filter(camera_id=cam, track_id=3).count() == 1
    session = CustomerSession.objects.get(camera_id=cam, track_id=3)
    assert abs((session.entry_at - first_entry).total_seconds()) < 0.001  # unchanged
    assert abs((session.last_seen_at - later).total_seconds()) < 0.001  # bumped


def test_person_entered_without_a_track_id_is_ignored(cafe):
    ingest(
        Event(type=EventType.PERSON_ENTERED, cafe_id=str(cafe.id), camera_id=camera_id(), payload={})
    )
    assert not CustomerSession.objects.exists()


def test_a_new_entry_after_the_previous_session_ended_opens_a_second_session(cafe):
    """The same small track_id is legitimately reused across separate visits
    -- a closed session for it must not block a new one."""
    cam = camera_id()
    ingest(
        Event(type=EventType.PERSON_ENTERED, cafe_id=str(cafe.id), camera_id=cam, payload={"track_id": 3})
    )
    ingest(
        Event(type=EventType.PERSON_EXITED, cafe_id=str(cafe.id), camera_id=cam, payload={"track_id": 3})
    )
    ingest(
        Event(type=EventType.PERSON_ENTERED, cafe_id=str(cafe.id), camera_id=cam, payload={"track_id": 3})
    )

    sessions = CustomerSession.objects.filter(camera_id=cam, track_id=3)
    assert sessions.count() == 2
    assert sessions.filter(status=CustomerSession.Status.ACTIVE).count() == 1
    assert sessions.filter(status=CustomerSession.Status.ENDED).count() == 1


# --------------------------------------------------------------------------- #
# person_exited
# --------------------------------------------------------------------------- #
def test_person_exited_closes_the_open_session(cafe):
    cam = camera_id()
    entry_at = timezone.now()
    exit_at = entry_at + timedelta(minutes=12)

    ingest(
        Event(
            type=EventType.PERSON_ENTERED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=entry_at, payload={"track_id": 9},
        )
    )
    ingest(
        Event(
            type=EventType.PERSON_EXITED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=exit_at, payload={"track_id": 9, "zone_name": "Back door"},
        )
    )

    session = CustomerSession.objects.get(camera_id=cam, track_id=9)
    assert session.status == CustomerSession.Status.ENDED
    assert session.exit_reason == CustomerSession.ExitReason.LINE_CROSSING
    assert session.exit_zone_name == "Back door"
    assert abs((session.exit_at - exit_at).total_seconds()) < 0.001
    assert session.duration_seconds == pytest.approx(720, abs=1)


def test_person_exited_with_no_open_session_does_not_raise_or_create_one(cafe):
    """E.g. the worker restarted between this person's entry and exit, so
    track_id no longer matches anything open."""
    result = ingest(
        Event(
            type=EventType.PERSON_EXITED, cafe_id=str(cafe.id), camera_id=camera_id(),
            payload={"track_id": 9},
        )
    )
    assert result.stored  # the raw event is still recorded; only the projection is a no-op
    assert not CustomerSession.objects.exists()


def test_person_exited_without_a_track_id_is_ignored(cafe):
    ingest(
        Event(type=EventType.PERSON_EXITED, cafe_id=str(cafe.id), camera_id=camera_id(), payload={})
    )
    assert not CustomerSession.objects.exists()


# --------------------------------------------------------------------------- #
# camera_stats heartbeat
# --------------------------------------------------------------------------- #
def test_camera_stats_bumps_last_seen_at_for_sessions_in_the_active_roster(cafe):
    cam = camera_id()
    entry_at = timezone.now() - timedelta(minutes=30)
    ingest(
        Event(
            type=EventType.PERSON_ENTERED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=entry_at, payload={"track_id": 4},
        )
    )

    heartbeat_at = timezone.now()
    ingest(
        Event(
            type=EventType.CAMERA_STATS, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=heartbeat_at, payload={"fps": 8.0, "active_track_ids": [4]},
        )
    )

    session = CustomerSession.objects.get(camera_id=cam, track_id=4)
    assert session.status == CustomerSession.Status.ACTIVE  # a long-sitting customer stays open
    assert abs((session.last_seen_at - heartbeat_at).total_seconds()) < 0.001


def test_camera_stats_does_not_bump_sessions_missing_from_the_roster(cafe):
    cam = camera_id()
    entry_at = timezone.now() - timedelta(minutes=5)
    ingest(
        Event(
            type=EventType.PERSON_ENTERED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=entry_at, payload={"track_id": 4},
        )
    )

    ingest(
        Event(
            type=EventType.CAMERA_STATS, cafe_id=str(cafe.id), camera_id=cam,
            payload={"fps": 8.0, "active_track_ids": [999]},
        )
    )

    session = CustomerSession.objects.get(camera_id=cam, track_id=4)
    assert abs((session.last_seen_at - entry_at).total_seconds()) < 0.001  # unchanged


def test_camera_stats_without_active_track_ids_does_not_raise(cafe):
    """Capture-only or detection-only mode: the field is simply absent."""
    ingest(
        Event(
            type=EventType.CAMERA_STATS, cafe_id=str(cafe.id), camera_id=camera_id(),
            payload={"fps": 8.0},
        )
    )  # must not raise


def test_camera_stats_never_reopens_an_ended_session(cafe):
    cam = camera_id()
    ingest(
        Event(type=EventType.PERSON_ENTERED, cafe_id=str(cafe.id), camera_id=cam, payload={"track_id": 4})
    )
    ingest(
        Event(type=EventType.PERSON_EXITED, cafe_id=str(cafe.id), camera_id=cam, payload={"track_id": 4})
    )
    session = CustomerSession.objects.get(camera_id=cam, track_id=4)
    exit_at = session.exit_at

    ingest(
        Event(
            type=EventType.CAMERA_STATS, cafe_id=str(cafe.id), camera_id=cam,
            payload={"fps": 8.0, "active_track_ids": [4]},
        )
    )

    session.refresh_from_db()
    assert session.status == CustomerSession.Status.ENDED
    assert session.exit_at == exit_at


# --------------------------------------------------------------------------- #
# cross-camera / cross-cafe isolation
# --------------------------------------------------------------------------- #
def test_a_heartbeat_on_a_different_camera_does_not_touch_a_same_numbered_track(cafe):
    """track_id is only unique per camera -- two different cameras can each
    have their own 'track 1' at the same time."""
    cam_a, cam_b = camera_id(), camera_id()
    entry_at = timezone.now() - timedelta(minutes=1)
    ingest(
        Event(
            type=EventType.PERSON_ENTERED, cafe_id=str(cafe.id), camera_id=cam_a,
            occurred_at=entry_at, payload={"track_id": 1},
        )
    )

    ingest(
        Event(
            type=EventType.CAMERA_STATS, cafe_id=str(cafe.id), camera_id=cam_b,
            payload={"fps": 8.0, "active_track_ids": [1]},
        )
    )

    session = CustomerSession.objects.get(camera_id=cam_a, track_id=1)
    assert abs((session.last_seen_at - entry_at).total_seconds()) < 0.001  # unchanged
