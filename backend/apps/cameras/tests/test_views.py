from __future__ import annotations

from unittest import mock

import pytest
from django.urls import reverse

from apps.cameras.models import Camera, TableZone, Zone
from apps.cameras.rtsp_probe import ProbeResult, ProbeStatus

pytestmark = pytest.mark.django_db


def make_camera(cafe, **overrides) -> Camera:
    defaults = {
        "cafe": cafe,
        "name": "Entrance",
        "rtsp_url": "rtsp://192.168.1.64:554/live",
        "rtsp_username": "admin",
    }
    defaults.update(overrides)
    camera = Camera(**defaults)
    camera.set_password("hunter2")
    camera.save()
    return camera


def make_zone(camera, **overrides) -> Zone:
    defaults = {
        "camera": camera,
        "name": "Entrance",
        "point_a_x": 100.0, "point_a_y": 0.0,
        "point_b_x": 100.0, "point_b_y": 200.0,
    }
    defaults.update(overrides)
    return Zone.objects.create(**defaults)


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def test_list_requires_authentication(api):
    assert api.get(reverse("camera-list")).status_code == 401


def test_list_is_scoped_to_the_callers_cafe(auth_api, cafe, other_cafe):
    make_camera(cafe, name="Mine")
    make_camera(other_cafe, name="Theirs")

    names = {item["name"] for item in auth_api.get(reverse("camera-list")).json()["results"]}
    assert names == {"Mine"}


def test_create_assigns_the_callers_cafe(auth_api, owner, other_cafe):
    """A manager must not be able to plant a camera in another café by editing
    the request body, mirroring the same guard on staff creation."""
    response = auth_api.post(
        reverse("camera-list"),
        {
            "name": "Kitchen",
            "rtsp_url": "rtsp://192.168.1.70:554/live",
            "cafe": str(other_cafe.id),
        },
        format="json",
    )
    assert response.status_code == 201
    assert Camera.objects.get(name="Kitchen").cafe_id == owner.cafe_id


def test_password_is_never_returned(auth_api, cafe):
    camera = make_camera(cafe)
    body = auth_api.get(reverse("camera-detail", args=[camera.id])).json()
    assert "rtsp_password" not in body
    assert "rtsp_password_encrypted" not in body
    assert body["has_password"] is True


def test_create_with_a_password_stores_it_encrypted(auth_api, cafe):
    response = auth_api.post(
        reverse("camera-list"),
        {
            "name": "Entrance",
            "rtsp_url": "rtsp://192.168.1.64:554/live",
            "rtsp_username": "admin",
            "rtsp_password": "hunter2",
        },
        format="json",
    )
    assert response.status_code == 201
    camera = Camera.objects.get(name="Entrance")
    assert camera.get_password() == "hunter2"


def test_patch_without_a_password_leaves_the_existing_one_intact(auth_api, cafe):
    camera = make_camera(cafe)
    response = auth_api.patch(
        reverse("camera-detail", args=[camera.id]), {"location": "Front door"}, format="json"
    )
    assert response.status_code == 200
    camera.refresh_from_db()
    assert camera.get_password() == "hunter2"
    assert camera.location == "Front door"


def test_embedded_credentials_in_the_url_are_rejected(auth_api, cafe):
    response = auth_api.post(
        reverse("camera-list"),
        {"name": "Bad", "rtsp_url": "rtsp://admin:secret@192.168.1.64/live"},
        format="json",
    )
    assert response.status_code == 400


def test_staff_can_read_but_not_create(api, staff):
    from rest_framework_simplejwt.tokens import RefreshToken

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(staff).access_token}")
    assert api.get(reverse("camera-list")).status_code == 200
    response = api.post(
        reverse("camera-list"),
        {"name": "X", "rtsp_url": "rtsp://192.168.1.64/live"},
        format="json",
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# test-connection
# --------------------------------------------------------------------------- #
def test_test_connection_reports_success(auth_api, cafe):
    camera = make_camera(cafe)
    with mock.patch(
        "apps.cameras.views.probe_rtsp",
        return_value=ProbeResult(ProbeStatus.OK, "Connected successfully."),
    ) as probe:
        response = auth_api.post(reverse("camera-test-connection", args=[camera.id]))

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "ok": True, "message": "Connected successfully.", "detail": "",
    }
    # Whatever is currently saved is what gets tested, not anything a client
    # could pass in the request body.
    probe.assert_called_once_with(camera.rtsp_url, camera.rtsp_username, "hunter2")


def test_test_connection_reports_a_specific_failure(auth_api, cafe):
    camera = make_camera(cafe)
    with mock.patch(
        "apps.cameras.views.probe_rtsp",
        return_value=ProbeResult(ProbeStatus.AUTH_FAILED, "Authentication failed: check the username and password."),
    ):
        response = auth_api.post(reverse("camera-test-connection", args=[camera.id]))

    assert response.status_code == 502
    body = response.json()
    assert body["status"] == "auth_failed"
    assert body["ok"] is False


def test_test_connection_requires_authentication(api, cafe):
    camera = make_camera(cafe)
    assert api.post(reverse("camera-test-connection", args=[camera.id])).status_code == 401


# --------------------------------------------------------------------------- #
# worker-config
# --------------------------------------------------------------------------- #
def test_worker_config_requires_the_worker_token(api, cafe):
    make_camera(cafe)
    response = api.get(reverse("camera-worker-config"), {"cafe_id": str(cafe.id)})
    assert response.status_code == 403


def test_worker_config_returns_decrypted_urls(api, cafe, settings):
    make_camera(cafe, name="Entrance")
    response = api.get(
        reverse("camera-worker-config"),
        {"cafe_id": str(cafe.id)},
        HTTP_X_WORKER_TOKEN=settings.AI_WORKER_TOKEN,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["url"] == "rtsp://admin:hunter2@192.168.1.64:554/live"


def test_worker_config_excludes_disabled_cameras(api, cafe, settings):
    make_camera(cafe, name="Off", is_enabled=False)
    response = api.get(
        reverse("camera-worker-config"),
        {"cafe_id": str(cafe.id)},
        HTTP_X_WORKER_TOKEN=settings.AI_WORKER_TOKEN,
    )
    assert response.json() == []


def test_worker_config_requires_cafe_id(api, settings):
    response = api.get(reverse("camera-worker-config"), HTTP_X_WORKER_TOKEN=settings.AI_WORKER_TOKEN)
    assert response.status_code == 400


def test_worker_config_includes_active_zones_as_point_pairs(api, cafe, settings):
    """Shape must agree with worker/manager.py::_parse_zone exactly: point_a
    and point_b as [x, y] pairs, not the model's flat columns."""
    camera = make_camera(cafe, name="Entrance")
    make_zone(camera, name="Front door", point_a_x=100.0, point_a_y=0.0, point_b_x=100.0, point_b_y=200.0)
    response = api.get(
        reverse("camera-worker-config"),
        {"cafe_id": str(cafe.id)},
        HTTP_X_WORKER_TOKEN=settings.AI_WORKER_TOKEN,
    )
    assert response.status_code == 200
    zones = response.json()[0]["zones"]
    assert len(zones) == 1
    assert zones[0]["name"] == "Front door"
    assert zones[0]["point_a"] == [100.0, 0.0]
    assert zones[0]["point_b"] == [100.0, 200.0]
    assert zones[0]["entry_is_positive_side"] is True


def test_worker_config_excludes_inactive_zones(api, cafe, settings):
    camera = make_camera(cafe, name="Entrance")
    make_zone(camera, name="Disabled", is_active=False)
    response = api.get(
        reverse("camera-worker-config"),
        {"cafe_id": str(cafe.id)},
        HTTP_X_WORKER_TOKEN=settings.AI_WORKER_TOKEN,
    )
    assert response.json()[0]["zones"] == []


def test_worker_config_reports_no_zones_for_a_camera_with_none(api, cafe, settings):
    make_camera(cafe, name="Entrance")
    response = api.get(
        reverse("camera-worker-config"),
        {"cafe_id": str(cafe.id)},
        HTTP_X_WORKER_TOKEN=settings.AI_WORKER_TOKEN,
    )
    assert response.json()[0]["zones"] == []


def test_worker_config_is_scoped_to_the_requested_cafe(api, cafe, other_cafe, settings):
    make_camera(cafe, name="Mine")
    make_camera(other_cafe, name="Theirs")
    response = api.get(
        reverse("camera-worker-config"),
        {"cafe_id": str(cafe.id)},
        HTTP_X_WORKER_TOKEN=settings.AI_WORKER_TOKEN,
    )
    names = {item["name"] for item in response.json()}
    assert names == {"Mine"}


# --------------------------------------------------------------------------- #
# zones (Phase 5)
# --------------------------------------------------------------------------- #
def test_zone_list_requires_authentication(api, cafe):
    camera = make_camera(cafe)
    response = api.get(reverse("zone-list", args=[camera.id]))
    assert response.status_code == 401


def test_zone_list_is_scoped_to_the_callers_cafe(auth_api, cafe, other_cafe):
    camera = make_camera(cafe)
    other_camera = make_camera(other_cafe)
    make_zone(camera)
    response = auth_api.get(reverse("zone-list", args=[other_camera.id]))
    assert response.status_code == 404


def test_zone_list_is_not_paginated(auth_api, cafe):
    """A camera has at most a handful of lines -- the editor expects a bare
    array, not a {count, next, results} envelope."""
    camera = make_camera(cafe)
    make_zone(camera, name="A")
    make_zone(camera, name="B", point_a_x=0.0, point_b_x=0.0)

    body = auth_api.get(reverse("zone-list", args=[camera.id])).json()
    assert isinstance(body, list)
    assert {z["name"] for z in body} == {"A", "B"}


def test_zone_create_assigns_the_camera_from_the_url(auth_api, cafe):
    camera = make_camera(cafe)
    response = auth_api.post(
        reverse("zone-list", args=[camera.id]),
        {
            "name": "Front door",
            "point_a_x": 100.0, "point_a_y": 0.0,
            "point_b_x": 100.0, "point_b_y": 200.0,
        },
        format="json",
    )
    assert response.status_code == 201
    zone = Zone.objects.get(name="Front door")
    assert zone.camera_id == camera.id


def test_zone_create_ignores_a_camera_id_in_the_body(auth_api, cafe, other_cafe):
    """A client naming a different camera in the body must not be able to
    attach a zone to it -- only the URL's camera_id is trusted, same
    principle as CafeScopedCreateMixin for `cafe`."""
    camera = make_camera(cafe)
    other_camera = make_camera(other_cafe)
    response = auth_api.post(
        reverse("zone-list", args=[camera.id]),
        {
            "name": "Front door", "camera": str(other_camera.id),
            "point_a_x": 100.0, "point_a_y": 0.0,
            "point_b_x": 100.0, "point_b_y": 200.0,
        },
        format="json",
    )
    assert response.status_code == 201
    assert Zone.objects.get(name="Front door").camera_id == camera.id


def test_zone_create_on_another_cafes_camera_404s(auth_api, other_cafe):
    camera = make_camera(other_cafe)
    response = auth_api.post(
        reverse("zone-list", args=[camera.id]),
        {
            "name": "Front door",
            "point_a_x": 100.0, "point_a_y": 0.0,
            "point_b_x": 100.0, "point_b_y": 200.0,
        },
        format="json",
    )
    assert response.status_code == 404
    assert not Zone.objects.exists()


def test_zone_update(auth_api, cafe):
    camera = make_camera(cafe)
    zone = make_zone(camera)
    response = auth_api.patch(
        reverse("zone-detail", args=[camera.id, zone.id]), {"is_active": False}, format="json"
    )
    assert response.status_code == 200
    zone.refresh_from_db()
    assert zone.is_active is False


def test_zone_delete(auth_api, cafe):
    camera = make_camera(cafe)
    zone = make_zone(camera)
    response = auth_api.delete(reverse("zone-detail", args=[camera.id, zone.id]))
    assert response.status_code == 204
    assert not Zone.objects.filter(id=zone.id).exists()


def test_staff_can_read_zones_but_not_create(api, cafe, staff):
    from rest_framework_simplejwt.tokens import RefreshToken

    camera = make_camera(cafe)
    make_zone(camera)
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(staff).access_token}")
    assert api.get(reverse("zone-list", args=[camera.id])).status_code == 200
    response = api.post(
        reverse("zone-list", args=[camera.id]),
        {
            "name": "X",
            "point_a_x": 0.0, "point_a_y": 0.0,
            "point_b_x": 0.0, "point_b_y": 1.0,
        },
        format="json",
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# streaming
# --------------------------------------------------------------------------- #
def test_snapshot_404s_when_no_frame_exists_yet(auth_api, cafe, monkeypatch):
    camera = make_camera(cafe)
    monkeypatch.setattr("apps.cameras.views.get_latest_frame", lambda camera_id: None)
    response = auth_api.get(reverse("camera-snapshot", args=[camera.id]))
    assert response.status_code == 404


def test_snapshot_returns_the_cached_jpeg(auth_api, cafe, monkeypatch):
    camera = make_camera(cafe)
    fake_jpeg = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    monkeypatch.setattr("apps.cameras.views.get_latest_frame", lambda camera_id: fake_jpeg)

    response = auth_api.get(reverse("camera-snapshot", args=[camera.id]))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/jpeg"
    assert response.content == fake_jpeg


def test_snapshot_requires_authentication(api, cafe):
    camera = make_camera(cafe)
    assert api.get(reverse("camera-snapshot", args=[camera.id])).status_code == 401


def test_snapshot_is_scoped_to_the_callers_cafe(auth_api, other_cafe):
    camera = make_camera(other_cafe)
    assert auth_api.get(reverse("camera-snapshot", args=[camera.id])).status_code == 404


# --------------------------------------------------------------------------- #
# detections (Phase 3)
# --------------------------------------------------------------------------- #
def test_detections_404s_when_none_have_been_recorded_yet(auth_api, cafe, monkeypatch):
    camera = make_camera(cafe)
    monkeypatch.setattr("apps.cameras.views.get_latest_detections", lambda camera_id: None)
    response = auth_api.get(reverse("camera-detections", args=[camera.id]))
    assert response.status_code == 404


def test_detections_returns_the_cached_summary(auth_api, cafe, monkeypatch):
    camera = make_camera(cafe)
    summary = {
        "person_count": 2,
        "inference_ms": 41.2,
        "boxes": [{"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0, "confidence": 0.9}],
        "updated_at": "2026-01-01T12:00:00+00:00",
    }
    monkeypatch.setattr("apps.cameras.views.get_latest_detections", lambda camera_id: summary)

    response = auth_api.get(reverse("camera-detections", args=[camera.id]))
    assert response.status_code == 200
    assert response.json() == summary


def test_detections_requires_authentication(api, cafe):
    camera = make_camera(cafe)
    assert api.get(reverse("camera-detections", args=[camera.id])).status_code == 401


def test_detections_is_scoped_to_the_callers_cafe(auth_api, other_cafe):
    camera = make_camera(other_cafe)
    assert auth_api.get(reverse("camera-detections", args=[camera.id])).status_code == 404


# --------------------------------------------------------------------------- #
# tracks (Phase 4)
# --------------------------------------------------------------------------- #
def test_tracks_404s_when_none_have_been_recorded_yet(auth_api, cafe, monkeypatch):
    camera = make_camera(cafe)
    monkeypatch.setattr("apps.cameras.views.get_latest_tracks", lambda camera_id: None)
    response = auth_api.get(reverse("camera-tracks", args=[camera.id]))
    assert response.status_code == 404


def test_tracks_returns_the_cached_summary(auth_api, cafe, monkeypatch):
    camera = make_camera(cafe)
    summary = {
        "track_count": 1,
        "tracks": [{"track_id": 7, "x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0, "confidence": 0.9}],
        "updated_at": "2026-01-01T12:00:00+00:00",
    }
    monkeypatch.setattr("apps.cameras.views.get_latest_tracks", lambda camera_id: summary)

    response = auth_api.get(reverse("camera-tracks", args=[camera.id]))
    assert response.status_code == 200
    assert response.json() == summary


def test_tracks_requires_authentication(api, cafe):
    camera = make_camera(cafe)
    assert api.get(reverse("camera-tracks", args=[camera.id])).status_code == 401


def test_tracks_is_scoped_to_the_callers_cafe(auth_api, other_cafe):
    camera = make_camera(other_cafe)
    assert auth_api.get(reverse("camera-tracks", args=[camera.id])).status_code == 404


# --------------------------------------------------------------------------- #
# the bootstrap superuser (regression: see apps.core.viewsets.CafeScopedCreateMixin)
# --------------------------------------------------------------------------- #
def test_the_bootstrap_superuser_can_create_a_camera(superuser_auth_api, superuser_owner):
    """This is the account every fresh install starts with. It must be able to
    add its own café's first camera without the request body naming the café
    explicitly -- CafeScopedCreateMixin defaults a superuser into their own
    café precisely so this works."""
    response = superuser_auth_api.post(
        reverse("camera-list"),
        {"name": "Entrance", "rtsp_url": "rtsp://192.168.1.64:554/live"},
        format="json",
    )
    assert response.status_code == 201
    camera = Camera.objects.get(name="Entrance")
    assert camera.cafe_id == superuser_owner.cafe_id


def test_a_superuser_can_still_target_a_different_cafe_explicitly(superuser_auth_api, other_cafe):
    """A genuine platform admin managing more than one tenant can override the
    default by naming a café explicitly."""
    response = superuser_auth_api.post(
        reverse("camera-list"),
        {
            "name": "Entrance",
            "rtsp_url": "rtsp://192.168.1.64:554/live",
            "cafe": str(other_cafe.id),
        },
        format="json",
    )
    assert response.status_code == 201
    assert Camera.objects.get(name="Entrance").cafe_id == other_cafe.id


def make_table(camera, **overrides) -> TableZone:
    defaults = {"camera": camera, "name": "Table 1", "x1": 0.0, "y1": 0.0, "x2": 100.0, "y2": 100.0}
    defaults.update(overrides)
    return TableZone.objects.create(**defaults)


# --------------------------------------------------------------------------- #
# worker-config: tables (Phase 9)
# --------------------------------------------------------------------------- #
def test_worker_config_includes_active_tables_as_flat_columns(api, cafe, settings):
    """Shape must agree with worker/manager.py::_parse_table exactly."""
    camera = make_camera(cafe, name="Entrance")
    make_table(camera, name="Window seat", x1=10.0, y1=20.0, x2=110.0, y2=120.0)
    response = api.get(
        reverse("camera-worker-config"),
        {"cafe_id": str(cafe.id)},
        HTTP_X_WORKER_TOKEN=settings.AI_WORKER_TOKEN,
    )
    assert response.status_code == 200
    tables = response.json()[0]["tables"]
    assert len(tables) == 1
    assert tables[0]["name"] == "Window seat"
    assert (tables[0]["x1"], tables[0]["y1"], tables[0]["x2"], tables[0]["y2"]) == (10.0, 20.0, 110.0, 120.0)


def test_worker_config_excludes_inactive_tables(api, cafe, settings):
    camera = make_camera(cafe, name="Entrance")
    make_table(camera, name="Disabled", is_active=False)
    response = api.get(
        reverse("camera-worker-config"),
        {"cafe_id": str(cafe.id)},
        HTTP_X_WORKER_TOKEN=settings.AI_WORKER_TOKEN,
    )
    assert response.json()[0]["tables"] == []


def test_worker_config_reports_no_tables_for_a_camera_with_none(api, cafe, settings):
    make_camera(cafe, name="Entrance")
    response = api.get(
        reverse("camera-worker-config"),
        {"cafe_id": str(cafe.id)},
        HTTP_X_WORKER_TOKEN=settings.AI_WORKER_TOKEN,
    )
    assert response.json()[0]["tables"] == []


# --------------------------------------------------------------------------- #
# tables (Phase 9)
# --------------------------------------------------------------------------- #
def test_table_list_requires_authentication(api, cafe):
    camera = make_camera(cafe)
    response = api.get(reverse("table-list", args=[camera.id]))
    assert response.status_code == 401


def test_table_list_is_scoped_to_the_callers_cafe(auth_api, cafe, other_cafe):
    camera = make_camera(cafe)
    other_camera = make_camera(other_cafe)
    make_table(camera)
    response = auth_api.get(reverse("table-list", args=[other_camera.id]))
    assert response.status_code == 404


def test_table_list_is_not_paginated(auth_api, cafe):
    camera = make_camera(cafe)
    make_table(camera, name="A")
    make_table(camera, name="B", x1=200.0, x2=300.0)

    body = auth_api.get(reverse("table-list", args=[camera.id])).json()
    assert isinstance(body, list)
    assert {t["name"] for t in body} == {"A", "B"}


def test_table_create_assigns_the_camera_from_the_url(auth_api, cafe):
    camera = make_camera(cafe)
    response = auth_api.post(
        reverse("table-list", args=[camera.id]),
        {"name": "Window seat", "x1": 0.0, "y1": 0.0, "x2": 100.0, "y2": 100.0},
        format="json",
    )
    assert response.status_code == 201
    table = TableZone.objects.get(name="Window seat")
    assert table.camera_id == camera.id


def test_table_create_ignores_a_camera_id_in_the_body(auth_api, cafe, other_cafe):
    camera = make_camera(cafe)
    other_camera = make_camera(other_cafe)
    response = auth_api.post(
        reverse("table-list", args=[camera.id]),
        {
            "name": "Window seat", "camera": str(other_camera.id),
            "x1": 0.0, "y1": 0.0, "x2": 100.0, "y2": 100.0,
        },
        format="json",
    )
    assert response.status_code == 201
    assert TableZone.objects.get(name="Window seat").camera_id == camera.id


def test_table_create_on_another_cafes_camera_404s(auth_api, other_cafe):
    camera = make_camera(other_cafe)
    response = auth_api.post(
        reverse("table-list", args=[camera.id]),
        {"name": "Window seat", "x1": 0.0, "y1": 0.0, "x2": 100.0, "y2": 100.0},
        format="json",
    )
    assert response.status_code == 404
    assert not TableZone.objects.exists()


def test_table_update(auth_api, cafe):
    camera = make_camera(cafe)
    table = make_table(camera)
    response = auth_api.patch(
        reverse("table-detail", args=[camera.id, table.id]), {"is_active": False}, format="json"
    )
    assert response.status_code == 200
    table.refresh_from_db()
    assert table.is_active is False


def test_table_delete(auth_api, cafe):
    camera = make_camera(cafe)
    table = make_table(camera)
    response = auth_api.delete(reverse("table-detail", args=[camera.id, table.id]))
    assert response.status_code == 204
    assert not TableZone.objects.filter(id=table.id).exists()


def test_staff_can_read_tables_but_not_create(api, cafe, staff):
    from rest_framework_simplejwt.tokens import RefreshToken

    camera = make_camera(cafe)
    make_table(camera)
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(staff).access_token}")
    assert api.get(reverse("table-list", args=[camera.id])).status_code == 200
    response = api.post(
        reverse("table-list", args=[camera.id]),
        {"name": "X", "x1": 0.0, "y1": 0.0, "x2": 100.0, "y2": 100.0},
        format="json",
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# mount_type (Phase 9)
# --------------------------------------------------------------------------- #
def test_mount_type_can_be_set_through_the_api(auth_api, cafe):
    camera = make_camera(cafe)
    response = auth_api.patch(
        reverse("camera-detail", args=[camera.id]), {"mount_type": "overhead"}, format="json"
    )
    assert response.status_code == 200
    camera.refresh_from_db()
    assert camera.mount_type == "overhead"
