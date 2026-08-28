from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tables.models import TableSession

pytestmark = pytest.mark.django_db


def make_session(cafe, **overrides) -> TableSession:
    now = timezone.now()
    defaults = {
        "cafe": cafe, "camera_id": uuid.uuid4(), "table_zone_id": uuid.uuid4(),
        "table_name": "Table 1", "occupied_at": now, "last_seen_at": now,
    }
    defaults.update(overrides)
    return TableSession.objects.create(**defaults)


def test_duration_seconds_for_an_ended_session_is_released_minus_occupied(cafe):
    occupied = timezone.now() - timedelta(minutes=50)
    released = occupied + timedelta(minutes=45)
    session = make_session(cafe, occupied_at=occupied, released_at=released, status=TableSession.Status.ENDED)
    assert session.duration_seconds == pytest.approx(2700, abs=1)


def test_duration_seconds_for_an_active_session_counts_up_to_now(cafe):
    occupied = timezone.now() - timedelta(minutes=10)
    session = make_session(cafe, occupied_at=occupied)
    assert session.duration_seconds == pytest.approx(600, abs=2)


def test_default_status_is_active(cafe):
    session = make_session(cafe)
    assert session.status == TableSession.Status.ACTIVE
    assert session.released_at is None


def test_table_zone_id_is_not_unique_across_sessions(cafe):
    """Deliberately allowed: the same table is occupied and released many
    times over a café's history."""
    table = uuid.uuid4()
    make_session(cafe, table_zone_id=table)
    make_session(cafe, table_zone_id=table)  # must not raise
    assert TableSession.objects.filter(table_zone_id=table).count() == 2
