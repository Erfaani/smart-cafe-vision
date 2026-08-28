from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.sessions.models import CustomerSession

pytestmark = pytest.mark.django_db


def make_session(cafe, **overrides) -> CustomerSession:
    now = timezone.now()
    defaults = {
        "cafe": cafe,
        "camera_id": uuid.uuid4(),
        "track_id": 1,
        "entry_at": now,
        "last_seen_at": now,
    }
    defaults.update(overrides)
    return CustomerSession.objects.create(**defaults)


def test_list_requires_authentication(api):
    assert api.get(reverse("customer-session-list")).status_code == 401


def test_list_is_scoped_to_the_callers_cafe(auth_api, cafe, other_cafe):
    make_session(cafe, track_id=1)
    make_session(other_cafe, track_id=2)

    body = auth_api.get(reverse("customer-session-list")).json()
    track_ids = {item["track_id"] for item in body["results"]}
    assert track_ids == {1}


def test_list_is_read_only(auth_api, cafe):
    response = auth_api.post(reverse("customer-session-list"), {}, format="json")
    assert response.status_code == 405


def test_retrieve_includes_duration_seconds_but_not_last_seen_at(auth_api, cafe):
    session = make_session(
        cafe,
        entry_at=timezone.now() - timedelta(minutes=3),
    )
    body = auth_api.get(reverse("customer-session-detail", args=[session.id])).json()
    assert body["duration_seconds"] == pytest.approx(180, abs=2)
    assert "last_seen_at" not in body


def test_retrieve_includes_a_color_from_the_cafes_stops(auth_api, cafe):
    cafe.stay_color_stops = [{"seconds": 0, "color": "#0000ff"}, {"seconds": 60, "color": "#ff0000"}]
    cafe.save(update_fields=["stay_color_stops"])
    session = make_session(cafe, entry_at=timezone.now() - timedelta(minutes=5))

    body = auth_api.get(reverse("customer-session-detail", args=[session.id])).json()
    assert body["color"] == "#ff0000"


def test_filter_by_status(auth_api, cafe):
    make_session(cafe, track_id=1, status=CustomerSession.Status.ACTIVE)
    make_session(
        cafe, track_id=2, status=CustomerSession.Status.ENDED, exit_at=timezone.now(),
    )

    response = auth_api.get(reverse("customer-session-list"), {"status": "active"})
    track_ids = {item["track_id"] for item in response.json()["results"]}
    assert track_ids == {1}


def test_filter_by_camera_id(auth_api, cafe):
    cam = uuid.uuid4()
    make_session(cafe, camera_id=cam, track_id=1)
    make_session(cafe, camera_id=uuid.uuid4(), track_id=2)

    response = auth_api.get(reverse("customer-session-list"), {"camera_id": str(cam)})
    track_ids = {item["track_id"] for item in response.json()["results"]}
    assert track_ids == {1}
