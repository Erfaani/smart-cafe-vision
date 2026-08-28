from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.cameras.models import Camera, TableZone, Zone

pytestmark = pytest.mark.django_db


def make_camera(cafe, **overrides) -> Camera:
    defaults = {
        "cafe": cafe,
        "name": "Entrance",
        "rtsp_url": "rtsp://192.168.1.64:554/Streaming/Channels/101",
    }
    defaults.update(overrides)
    return Camera.objects.create(**defaults)


def test_rtsp_url_rejects_embedded_credentials(cafe):
    camera = Camera(cafe=cafe, name="Cam", rtsp_url="rtsp://admin:secret@192.168.1.64/live")
    with pytest.raises(ValidationError):
        camera.full_clean()


def test_rtsp_url_rejects_a_non_rtsp_scheme(cafe):
    camera = Camera(cafe=cafe, name="Cam", rtsp_url="http://192.168.1.64/live")
    with pytest.raises(ValidationError):
        camera.full_clean()


def test_rtsp_url_accepts_a_well_formed_url(cafe):
    camera = Camera(cafe=cafe, name="Cam", rtsp_url="rtsp://192.168.1.64:554/live")
    camera.full_clean()  # must not raise


def test_password_round_trips_through_encryption(cafe):
    camera = make_camera(cafe, rtsp_username="admin")
    camera.set_password("hunter2")
    camera.save()

    reloaded = Camera.objects.get(pk=camera.pk)
    assert "hunter2" not in reloaded.rtsp_password_encrypted
    assert reloaded.get_password() == "hunter2"


def test_build_connection_url_embeds_credentials(cafe):
    camera = make_camera(cafe, rtsp_username="admin")
    camera.set_password("hunter2")
    camera.save()

    url = camera.build_connection_url()
    assert url == "rtsp://admin:hunter2@192.168.1.64:554/Streaming/Channels/101"


def test_build_connection_url_without_credentials_is_unchanged(cafe):
    camera = make_camera(cafe)
    assert camera.build_connection_url() == camera.rtsp_url


def test_camera_name_is_unique_per_cafe(cafe):
    from django.db import IntegrityError

    make_camera(cafe, name="Entrance")
    with pytest.raises(IntegrityError):
        make_camera(cafe, name="Entrance")


def test_the_same_name_is_allowed_in_a_different_cafe(cafe, other_cafe):
    make_camera(cafe, name="Entrance")
    make_camera(other_cafe, name="Entrance")  # must not raise


def test_is_stale_is_false_when_never_connected(cafe):
    camera = make_camera(cafe)
    assert camera.is_stale is False


def test_is_stale_is_false_shortly_after_a_frame(cafe):
    camera = make_camera(
        cafe,
        connection_status=Camera.ConnectionStatus.CONNECTED,
        last_frame_at=timezone.now(),
    )
    assert camera.is_stale is False


def test_is_stale_is_true_when_connected_but_quiet(cafe):
    camera = make_camera(
        cafe,
        connection_status=Camera.ConnectionStatus.CONNECTED,
        last_frame_at=timezone.now() - timedelta(seconds=60),
    )
    assert camera.is_stale is True


def test_is_stale_is_false_when_status_is_not_connected(cafe):
    """A camera reported as disconnected is already honest about its state;
    'stale' is specifically for a status that has gone out of date."""
    camera = make_camera(
        cafe,
        connection_status=Camera.ConnectionStatus.ERROR,
        last_frame_at=timezone.now() - timedelta(seconds=60),
    )
    assert camera.is_stale is False


# --------------------------------------------------------------------------- #
# Zone (Phase 5)
# --------------------------------------------------------------------------- #
def make_zone(camera, **overrides) -> Zone:
    defaults = {
        "camera": camera,
        "name": "Entrance",
        "point_a_x": 100.0, "point_a_y": 0.0,
        "point_b_x": 100.0, "point_b_y": 200.0,
    }
    defaults.update(overrides)
    return Zone.objects.create(**defaults)


def test_point_a_and_point_b_are_tuples_of_the_flat_columns(cafe):
    camera = make_camera(cafe)
    zone = make_zone(camera, point_a_x=1.0, point_a_y=2.0, point_b_x=3.0, point_b_y=4.0)
    assert zone.point_a == (1.0, 2.0)
    assert zone.point_b == (3.0, 4.0)


def test_a_camera_can_have_more_than_one_zone(cafe):
    camera = make_camera(cafe)
    make_zone(camera, name="Front door")
    make_zone(camera, name="Back door", point_a_x=0.0, point_b_x=0.0)
    assert camera.zones.count() == 2


def test_deleting_a_camera_deletes_its_zones(cafe):
    camera = make_camera(cafe)
    make_zone(camera)
    camera.delete()
    assert Zone.objects.count() == 0


# --------------------------------------------------------------------------- #
# mount_type (Phase 9)
# --------------------------------------------------------------------------- #
def test_mount_type_defaults_to_unknown(cafe):
    camera = make_camera(cafe)
    assert camera.mount_type == Camera.MountType.UNKNOWN


# --------------------------------------------------------------------------- #
# TableZone (Phase 9)
# --------------------------------------------------------------------------- #
def make_table(camera, **overrides) -> TableZone:
    defaults = {"camera": camera, "name": "Table 1", "x1": 0.0, "y1": 0.0, "x2": 100.0, "y2": 100.0}
    defaults.update(overrides)
    return TableZone.objects.create(**defaults)


def test_a_camera_can_have_more_than_one_table(cafe):
    camera = make_camera(cafe)
    make_table(camera, name="Table 1")
    make_table(camera, name="Table 2", x1=200.0, x2=300.0)
    assert camera.tables.count() == 2


def test_deleting_a_camera_deletes_its_tables(cafe):
    camera = make_camera(cafe)
    make_table(camera)
    camera.delete()
    assert TableZone.objects.count() == 0
