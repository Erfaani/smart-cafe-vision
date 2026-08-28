from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
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


# --------------------------------------------------------------------------- #
# sessions
# --------------------------------------------------------------------------- #
def test_list_requires_authentication(api):
    assert api.get(reverse("table-session-list")).status_code == 401


def test_list_is_scoped_to_the_callers_cafe(auth_api, cafe, other_cafe):
    make_session(cafe, table_name="Mine")
    make_session(other_cafe, table_name="Theirs")

    body = auth_api.get(reverse("table-session-list")).json()
    names = {item["table_name"] for item in body["results"]}
    assert names == {"Mine"}


def test_list_is_read_only(auth_api, cafe):
    response = auth_api.post(reverse("table-session-list"), {}, format="json")
    assert response.status_code == 405


def test_retrieve_includes_duration_seconds_but_not_last_seen_at(auth_api, cafe):
    session = make_session(cafe, occupied_at=timezone.now() - timedelta(minutes=3))
    body = auth_api.get(reverse("table-session-detail", args=[session.id])).json()
    assert body["duration_seconds"] == pytest.approx(180, abs=2)
    assert "last_seen_at" not in body


def test_filter_by_status(auth_api, cafe):
    make_session(cafe, table_name="Occupied", status=TableSession.Status.ACTIVE)
    make_session(
        cafe, table_name="Free", status=TableSession.Status.ENDED, released_at=timezone.now(),
    )

    response = auth_api.get(reverse("table-session-list"), {"status": "active"})
    names = {item["table_name"] for item in response.json()["results"]}
    assert names == {"Occupied"}


def test_filter_by_table_zone_id(auth_api, cafe):
    table = uuid.uuid4()
    make_session(cafe, table_zone_id=table, table_name="Mine")
    make_session(cafe, table_zone_id=uuid.uuid4(), table_name="Other")

    response = auth_api.get(reverse("table-session-list"), {"table_zone_id": str(table)})
    names = {item["table_name"] for item in response.json()["results"]}
    assert names == {"Mine"}


# --------------------------------------------------------------------------- #
# utilization
# --------------------------------------------------------------------------- #
def test_utilization_requires_authentication(api):
    assert api.get(reverse("table-utilization")).status_code == 401


def test_utilization_requires_start_and_end(auth_api):
    assert auth_api.get(reverse("table-utilization")).status_code == 400
    assert auth_api.get(reverse("table-utilization"), {"start": "2026-06-01T00:00:00Z"}).status_code == 400


def test_utilization_reports_a_configured_table_with_zero_sessions(auth_api, cafe):
    from apps.cameras.models import Camera, TableZone

    camera = Camera.objects.create(cafe=cafe, name="Entrance", rtsp_url="rtsp://x/live")
    TableZone.objects.create(camera=camera, name="Table 1", x1=0, y1=0, x2=100, y2=100)

    response = auth_api.get(
        reverse("table-utilization"),
        {"start": "2026-06-01T00:00:00Z", "end": "2026-06-02T00:00:00Z"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["table_name"] == "Table 1"
    assert body[0]["occupied_seconds"] == 0
    assert body[0]["turnover_count"] == 0


def test_utilization_is_scoped_to_the_callers_cafe(auth_api, cafe, other_cafe):
    from apps.cameras.models import Camera, TableZone

    Camera.objects.create(cafe=cafe, name="Mine", rtsp_url="rtsp://x/live")
    other_camera = Camera.objects.create(cafe=other_cafe, name="Theirs", rtsp_url="rtsp://y/live")
    TableZone.objects.create(camera=other_camera, name="Their table", x1=0, y1=0, x2=100, y2=100)

    response = auth_api.get(
        reverse("table-utilization"),
        {"start": "2026-06-01T00:00:00Z", "end": "2026-06-02T00:00:00Z"},
    )
    assert response.json() == []
