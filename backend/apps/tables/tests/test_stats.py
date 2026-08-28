from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta

import pytest

from apps.cameras.models import Camera, TableZone
from apps.tables.models import TableSession
from apps.tables.stats import table_utilization

pytestmark = pytest.mark.django_db


def utc(y, m, d, h=0, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=zoneinfo.ZoneInfo("UTC"))


def make_camera(cafe, **overrides) -> Camera:
    defaults = {"cafe": cafe, "name": "Entrance", "rtsp_url": "rtsp://192.168.1.64:554/live"}
    defaults.update(overrides)
    return Camera.objects.create(**defaults)


def make_table(camera, **overrides) -> TableZone:
    defaults = {"camera": camera, "name": "Table 1", "x1": 0.0, "y1": 0.0, "x2": 100.0, "y2": 100.0}
    defaults.update(overrides)
    return TableZone.objects.create(**defaults)


def make_session(cafe, camera, table, **overrides) -> TableSession:
    now = utc(2026, 6, 1, 10)
    defaults = {
        "cafe": cafe, "camera_id": camera.id, "table_zone_id": table.id, "table_name": table.name,
        "status": TableSession.Status.ENDED, "occupied_at": now, "released_at": now + timedelta(minutes=30),
        "last_seen_at": now,
    }
    defaults.update(overrides)
    return TableSession.objects.create(**defaults)


def test_a_table_with_no_sessions_reports_zero(cafe):
    camera = make_camera(cafe)
    make_table(camera)

    result = table_utilization(cafe, utc(2026, 6, 1), utc(2026, 6, 2))

    assert len(result) == 1
    assert result[0]["occupied_seconds"] == 0.0
    assert result[0]["turnover_count"] == 0
    assert result[0]["utilization_percent"] == 0.0


def test_a_session_fully_inside_the_range_counts_in_full(cafe):
    camera = make_camera(cafe)
    table = make_table(camera)
    make_session(cafe, camera, table, occupied_at=utc(2026, 6, 1, 10), released_at=utc(2026, 6, 1, 11))

    result = table_utilization(cafe, utc(2026, 6, 1), utc(2026, 6, 2))

    assert result[0]["occupied_seconds"] == pytest.approx(3600)
    assert result[0]["turnover_count"] == 1


def test_a_session_is_clipped_to_the_requested_range(cafe):
    """A table occupied from 23:00 yesterday to 01:00 today, queried for
    just today: only the hour inside [start, end) counts, and it does not
    count as a turnover for today (it did not *start* in this range)."""
    camera = make_camera(cafe)
    table = make_table(camera)
    make_session(cafe, camera, table, occupied_at=utc(2026, 5, 31, 23), released_at=utc(2026, 6, 1, 1))

    result = table_utilization(cafe, utc(2026, 6, 1), utc(2026, 6, 2))

    assert result[0]["occupied_seconds"] == pytest.approx(3600)  # only 00:00-01:00
    assert result[0]["turnover_count"] == 0


def test_a_still_active_session_counts_up_to_the_range_end(cafe):
    camera = make_camera(cafe)
    table = make_table(camera)
    make_session(
        cafe, camera, table, status=TableSession.Status.ACTIVE,
        occupied_at=utc(2026, 6, 1, 23), released_at=None,
    )

    result = table_utilization(cafe, utc(2026, 6, 1), utc(2026, 6, 2))

    assert result[0]["occupied_seconds"] == pytest.approx(3600)  # 23:00-00:00


def test_utilization_percent_is_occupied_over_range_duration(cafe):
    camera = make_camera(cafe)
    table = make_table(camera)
    make_session(cafe, camera, table, occupied_at=utc(2026, 6, 1, 0), released_at=utc(2026, 6, 1, 12))

    result = table_utilization(cafe, utc(2026, 6, 1), utc(2026, 6, 2))  # 24h range, 12h occupied

    assert result[0]["utilization_percent"] == pytest.approx(50.0)


def test_turnover_count_only_counts_sessions_starting_in_range(cafe):
    camera = make_camera(cafe)
    table = make_table(camera)
    make_session(cafe, camera, table, occupied_at=utc(2026, 6, 1, 9), released_at=utc(2026, 6, 1, 10))
    make_session(cafe, camera, table, occupied_at=utc(2026, 6, 1, 14), released_at=utc(2026, 6, 1, 15))

    result = table_utilization(cafe, utc(2026, 6, 1), utc(2026, 6, 2))

    assert result[0]["turnover_count"] == 2


def test_a_session_outside_the_range_entirely_is_excluded(cafe):
    camera = make_camera(cafe)
    table = make_table(camera)
    make_session(cafe, camera, table, occupied_at=utc(2026, 5, 1), released_at=utc(2026, 5, 1, 1))

    result = table_utilization(cafe, utc(2026, 6, 1), utc(2026, 6, 2))

    assert result[0]["occupied_seconds"] == 0.0
    assert result[0]["turnover_count"] == 0


def test_every_configured_table_across_every_camera_is_included(cafe):
    camera_a = make_camera(cafe, name="Camera A")
    camera_b = make_camera(cafe, name="Camera B")
    make_table(camera_a, name="A1")
    make_table(camera_b, name="B1")

    result = table_utilization(cafe, utc(2026, 6, 1), utc(2026, 6, 2))

    assert {row["table_name"] for row in result} == {"A1", "B1"}


def test_tables_from_a_different_cafe_are_excluded(cafe, other_cafe):
    camera = make_camera(other_cafe)
    make_table(camera)

    result = table_utilization(cafe, utc(2026, 6, 1), utc(2026, 6, 2))

    assert result == []
