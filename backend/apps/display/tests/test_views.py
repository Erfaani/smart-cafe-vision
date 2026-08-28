from __future__ import annotations

import uuid

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.cameras.models import Camera
from apps.display.models import DisplayMessage
from apps.sessions.models import CustomerSession

pytestmark = pytest.mark.django_db


def make_message(cafe, **overrides) -> DisplayMessage:
    defaults = {"cafe": cafe, "text_en": "Enjoy your coffee!"}
    defaults.update(overrides)
    return DisplayMessage.objects.create(**defaults)


def make_camera(cafe, **overrides) -> Camera:
    defaults = {
        "cafe": cafe, "name": "Entrance", "rtsp_url": "rtsp://192.168.1.64:554/live",
        "is_enabled": True, "resolution_width": 1280, "resolution_height": 720,
    }
    defaults.update(overrides)
    return Camera.objects.create(**defaults)


def make_session(cafe, **overrides) -> CustomerSession:
    now = timezone.now()
    defaults = {"cafe": cafe, "camera_id": uuid.uuid4(), "track_id": 1, "entry_at": now, "last_seen_at": now}
    defaults.update(overrides)
    return CustomerSession.objects.create(**defaults)


# --------------------------------------------------------------------------- #
# staff CRUD
# --------------------------------------------------------------------------- #
def test_message_list_requires_authentication(api):
    assert api.get(reverse("display-message-list")).status_code == 401


def test_message_list_is_scoped_to_the_callers_cafe(auth_api, cafe, other_cafe):
    make_message(cafe, text_en="Mine")
    make_message(other_cafe, text_en="Theirs")

    texts = {item["text_en"] for item in auth_api.get(reverse("display-message-list")).json()["results"]}
    assert texts == {"Mine"}


def test_create_assigns_the_callers_cafe(auth_api, owner, other_cafe):
    response = auth_api.post(
        reverse("display-message-list"),
        {"text_en": "Hello", "cafe": str(other_cafe.id)},
        format="json",
    )
    assert response.status_code == 201
    assert DisplayMessage.objects.get(text_en="Hello").cafe_id == owner.cafe_id


def test_staff_can_read_but_not_create(api, cafe, staff):
    from rest_framework_simplejwt.tokens import RefreshToken

    make_message(cafe)
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(staff).access_token}")
    assert api.get(reverse("display-message-list")).status_code == 200
    response = api.post(reverse("display-message-list"), {"text_en": "X"}, format="json")
    assert response.status_code == 403


def test_update_and_delete(auth_api, cafe):
    message = make_message(cafe)
    response = auth_api.patch(
        reverse("display-message-detail", args=[message.id]), {"is_active": False}, format="json"
    )
    assert response.status_code == 200
    message.refresh_from_db()
    assert message.is_active is False

    assert auth_api.delete(reverse("display-message-detail", args=[message.id])).status_code == 204
    assert not DisplayMessage.objects.filter(id=message.id).exists()


# --------------------------------------------------------------------------- #
# public: live
# --------------------------------------------------------------------------- #
def test_public_live_requires_no_authentication(api, cafe):
    assert api.get(reverse("public-cafe-live", args=[cafe.slug])).status_code == 200


def test_public_live_404s_for_an_unknown_cafe(api):
    assert api.get(reverse("public-cafe-live", args=["no-such-cafe"])).status_code == 404


def test_public_live_404s_for_a_deactivated_cafe(api, cafe):
    cafe.is_active = False
    cafe.save(update_fields=["is_active"])
    assert api.get(reverse("public-cafe-live", args=[cafe.slug])).status_code == 404


def test_public_live_reflects_real_camera_and_track_data(api, cafe, monkeypatch):
    camera = make_camera(cafe)
    monkeypatch.setattr(
        "apps.display.live.get_latest_tracks",
        lambda camera_id: {
            "track_count": 1,
            "tracks": [{"track_id": 3, "x1": 0.0, "y1": 0.0, "x2": 100.0, "y2": 100.0, "confidence": 0.9}],
            "updated_at": timezone.now().isoformat(),
        },
    )

    body = api.get(reverse("public-cafe-live", args=[cafe.slug])).json()
    assert len(body) == 1
    assert body[0]["camera_id"] == str(camera.id)
    assert body[0]["people"][0]["track_id"] == 3


# --------------------------------------------------------------------------- #
# public: stats
# --------------------------------------------------------------------------- #
def test_public_stats_requires_no_authentication(api, cafe):
    assert api.get(reverse("public-cafe-stats", args=[cafe.slug])).status_code == 200


def test_public_stats_reports_current_occupancy(api, cafe):
    make_session(cafe)
    body = api.get(reverse("public-cafe-stats", args=[cafe.slug])).json()
    assert body["occupancy"] == 1
    assert body["seating_capacity"] == cafe.seating_capacity


def test_public_stats_404s_for_a_deactivated_cafe(api, cafe):
    cafe.is_active = False
    cafe.save(update_fields=["is_active"])
    assert api.get(reverse("public-cafe-stats", args=[cafe.slug])).status_code == 404


# --------------------------------------------------------------------------- #
# public: messages
# --------------------------------------------------------------------------- #
def test_public_messages_requires_no_authentication(api, cafe):
    assert api.get(reverse("public-cafe-messages", args=[cafe.slug])).status_code == 200


def test_public_messages_excludes_inactive_ones(api, cafe):
    make_message(cafe, text_en="Active one", is_active=True)
    make_message(cafe, text_en="Disabled one", is_active=False)

    body = api.get(reverse("public-cafe-messages", args=[cafe.slug])).json()
    assert [item["text"] for item in body] == ["Active one"]


def test_public_messages_uses_the_cafes_default_language(api, cafe):
    cafe.default_language = "fa"
    cafe.save(update_fields=["default_language"])
    make_message(cafe, text_en="Hello", text_fa="سلام")

    body = api.get(reverse("public-cafe-messages", args=[cafe.slug])).json()
    assert body[0]["text"] == "سلام"


def test_public_messages_lang_query_param_overrides_the_default(api, cafe):
    make_message(cafe, text_en="Hello", text_fa="سلام")
    body = api.get(reverse("public-cafe-messages", args=[cafe.slug]), {"lang": "fa"}).json()
    assert body[0]["text"] == "سلام"


def test_public_messages_are_scoped_to_the_requested_cafe(api, cafe, other_cafe):
    make_message(cafe, text_en="Mine")
    make_message(other_cafe, text_en="Theirs")

    body = api.get(reverse("public-cafe-messages", args=[cafe.slug])).json()
    assert [item["text"] for item in body] == ["Mine"]
