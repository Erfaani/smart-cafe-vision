"""The projections in apps/tables/projections.py are registered once, at app
startup (TablesConfig.ready()) -- these tests exercise the real, permanently
registered handlers by ingesting real events, same approach as
apps/sessions/tests/test_projections.py.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.events.ingest import ingest
from apps.tables.models import TableSession
from scv_contracts import Event, EventType

pytestmark = pytest.mark.django_db


def camera_id() -> str:
    return str(uuid.uuid4())


def table_id() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# table_occupied
# --------------------------------------------------------------------------- #
def test_table_occupied_opens_a_new_session(cafe):
    cam, table = camera_id(), table_id()
    occurred_at = timezone.now()

    ingest(
        Event(
            type=EventType.TABLE_OCCUPIED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=occurred_at, payload={"table_id": table, "table_name": "Table 3"},
        )
    )

    session = TableSession.objects.get(camera_id=cam, table_zone_id=table)
    assert session.status == TableSession.Status.ACTIVE
    assert session.table_name == "Table 3"
    assert abs((session.occupied_at - occurred_at).total_seconds()) < 0.001
    assert abs((session.last_seen_at - occurred_at).total_seconds()) < 0.001
    assert session.released_at is None


def test_a_second_occupied_for_an_already_open_session_is_treated_as_a_heartbeat(cafe):
    cam, table = camera_id(), table_id()
    first = timezone.now()
    ingest(
        Event(
            type=EventType.TABLE_OCCUPIED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=first, payload={"table_id": table, "table_name": "Table 3"},
        )
    )
    later = first + timedelta(seconds=5)
    ingest(
        Event(
            type=EventType.TABLE_OCCUPIED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=later, payload={"table_id": table, "table_name": "Table 3"},
        )
    )

    assert TableSession.objects.filter(camera_id=cam, table_zone_id=table).count() == 1
    session = TableSession.objects.get(camera_id=cam, table_zone_id=table)
    assert abs((session.occupied_at - first).total_seconds()) < 0.001  # unchanged
    assert abs((session.last_seen_at - later).total_seconds()) < 0.001  # bumped


def test_table_occupied_without_a_table_id_is_ignored(cafe):
    ingest(
        Event(type=EventType.TABLE_OCCUPIED, cafe_id=str(cafe.id), camera_id=camera_id(), payload={})
    )
    assert not TableSession.objects.exists()


def test_a_new_occupied_after_the_previous_session_ended_opens_a_second_session(cafe):
    cam, table = camera_id(), table_id()
    payload = {"table_id": table, "table_name": "Table 3"}
    ingest(Event(type=EventType.TABLE_OCCUPIED, cafe_id=str(cafe.id), camera_id=cam, payload=payload))
    ingest(Event(type=EventType.TABLE_RELEASED, cafe_id=str(cafe.id), camera_id=cam, payload=payload))
    ingest(Event(type=EventType.TABLE_OCCUPIED, cafe_id=str(cafe.id), camera_id=cam, payload=payload))

    sessions = TableSession.objects.filter(camera_id=cam, table_zone_id=table)
    assert sessions.count() == 2
    assert sessions.filter(status=TableSession.Status.ACTIVE).count() == 1
    assert sessions.filter(status=TableSession.Status.ENDED).count() == 1


# --------------------------------------------------------------------------- #
# table_released
# --------------------------------------------------------------------------- #
def test_table_released_closes_the_open_session(cafe):
    cam, table = camera_id(), table_id()
    occupied_at = timezone.now()
    released_at = occupied_at + timedelta(minutes=45)

    ingest(
        Event(
            type=EventType.TABLE_OCCUPIED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=occupied_at, payload={"table_id": table, "table_name": "Table 3"},
        )
    )
    ingest(
        Event(
            type=EventType.TABLE_RELEASED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=released_at, payload={"table_id": table, "table_name": "Table 3"},
        )
    )

    session = TableSession.objects.get(camera_id=cam, table_zone_id=table)
    assert session.status == TableSession.Status.ENDED
    assert session.release_reason == TableSession.ReleaseReason.CLEARED
    assert abs((session.released_at - released_at).total_seconds()) < 0.001
    assert session.duration_seconds == pytest.approx(2700, abs=1)


def test_table_released_with_no_open_session_does_not_raise_or_create_one(cafe):
    result = ingest(
        Event(
            type=EventType.TABLE_RELEASED, cafe_id=str(cafe.id), camera_id=camera_id(),
            payload={"table_id": table_id(), "table_name": "Table 3"},
        )
    )
    assert result.stored
    assert not TableSession.objects.exists()


def test_table_released_without_a_table_id_is_ignored(cafe):
    ingest(
        Event(type=EventType.TABLE_RELEASED, cafe_id=str(cafe.id), camera_id=camera_id(), payload={})
    )
    assert not TableSession.objects.exists()


# --------------------------------------------------------------------------- #
# camera_stats heartbeat
# --------------------------------------------------------------------------- #
def test_camera_stats_bumps_last_seen_at_for_sessions_in_the_occupied_roster(cafe):
    cam, table = camera_id(), table_id()
    occupied_at = timezone.now() - timedelta(hours=1)
    ingest(
        Event(
            type=EventType.TABLE_OCCUPIED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=occupied_at, payload={"table_id": table, "table_name": "Table 3"},
        )
    )

    heartbeat_at = timezone.now()
    ingest(
        Event(
            type=EventType.CAMERA_STATS, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=heartbeat_at, payload={"fps": 8.0, "occupied_table_ids": [table]},
        )
    )

    session = TableSession.objects.get(camera_id=cam, table_zone_id=table)
    assert session.status == TableSession.Status.ACTIVE  # a long lunch stays open
    assert abs((session.last_seen_at - heartbeat_at).total_seconds()) < 0.001


def test_camera_stats_does_not_bump_sessions_missing_from_the_roster(cafe):
    cam, table = camera_id(), table_id()
    occupied_at = timezone.now() - timedelta(minutes=5)
    ingest(
        Event(
            type=EventType.TABLE_OCCUPIED, cafe_id=str(cafe.id), camera_id=cam,
            occurred_at=occupied_at, payload={"table_id": table, "table_name": "Table 3"},
        )
    )

    ingest(
        Event(
            type=EventType.CAMERA_STATS, cafe_id=str(cafe.id), camera_id=cam,
            payload={"fps": 8.0, "occupied_table_ids": [table_id()]},
        )
    )

    session = TableSession.objects.get(camera_id=cam, table_zone_id=table)
    assert abs((session.last_seen_at - occupied_at).total_seconds()) < 0.001  # unchanged


def test_camera_stats_without_occupied_table_ids_does_not_raise(cafe):
    ingest(
        Event(
            type=EventType.CAMERA_STATS, cafe_id=str(cafe.id), camera_id=camera_id(),
            payload={"fps": 8.0},
        )
    )  # must not raise


def test_camera_stats_never_reopens_an_ended_session(cafe):
    cam, table = camera_id(), table_id()
    payload = {"table_id": table, "table_name": "Table 3"}
    ingest(Event(type=EventType.TABLE_OCCUPIED, cafe_id=str(cafe.id), camera_id=cam, payload=payload))
    ingest(Event(type=EventType.TABLE_RELEASED, cafe_id=str(cafe.id), camera_id=cam, payload=payload))
    session = TableSession.objects.get(camera_id=cam, table_zone_id=table)
    released_at = session.released_at

    ingest(
        Event(
            type=EventType.CAMERA_STATS, cafe_id=str(cafe.id), camera_id=cam,
            payload={"fps": 8.0, "occupied_table_ids": [table]},
        )
    )

    session.refresh_from_db()
    assert session.status == TableSession.Status.ENDED
    assert session.released_at == released_at


# --------------------------------------------------------------------------- #
# cross-camera / cross-cafe isolation
# --------------------------------------------------------------------------- #
def test_a_heartbeat_on_a_different_camera_does_not_touch_a_same_numbered_table(cafe):
    cam_a, cam_b, table = camera_id(), camera_id(), table_id()
    occupied_at = timezone.now() - timedelta(minutes=1)
    ingest(
        Event(
            type=EventType.TABLE_OCCUPIED, cafe_id=str(cafe.id), camera_id=cam_a,
            occurred_at=occupied_at, payload={"table_id": table, "table_name": "Table 3"},
        )
    )

    ingest(
        Event(
            type=EventType.CAMERA_STATS, cafe_id=str(cafe.id), camera_id=cam_b,
            payload={"fps": 8.0, "occupied_table_ids": [table]},
        )
    )

    session = TableSession.objects.get(camera_id=cam_a, table_zone_id=table)
    assert abs((session.last_seen_at - occupied_at).total_seconds()) < 0.001  # unchanged
