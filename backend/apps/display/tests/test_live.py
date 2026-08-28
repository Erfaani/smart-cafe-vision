from __future__ import annotations

import uuid
import zoneinfo
from datetime import timedelta

import pytest
import redis
from django.utils import timezone

from apps.cameras.models import Camera
from apps.display.live import get_public_live_tracks, get_public_stats
from apps.sessions.models import CustomerSession

pytestmark = pytest.mark.django_db


def make_camera(cafe, **overrides) -> Camera:
    defaults = {
        "cafe": cafe, "name": "Entrance", "rtsp_url": "rtsp://192.168.1.64:554/live",
        "is_enabled": True, "resolution_width": 1280, "resolution_height": 720,
    }
    defaults.update(overrides)
    return Camera.objects.create(**defaults)


def make_session(cafe, **overrides) -> CustomerSession:
    now = timezone.now()
    defaults = {
        "cafe": cafe, "camera_id": uuid.uuid4(), "track_id": 1, "entry_at": now, "last_seen_at": now,
    }
    defaults.update(overrides)
    return CustomerSession.objects.create(**defaults)


def make_tracks(*boxes) -> dict:
    return {"track_count": len(boxes), "tracks": list(boxes), "updated_at": timezone.now().isoformat()}


def box(track_id, x1=100.0, y1=100.0, x2=200.0, y2=300.0, confidence=0.9) -> dict:
    return {"track_id": track_id, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "confidence": confidence}


# --------------------------------------------------------------------------- #
# get_public_live_tracks
# --------------------------------------------------------------------------- #
def test_no_cameras_returns_an_empty_list(cafe):
    assert get_public_live_tracks(cafe) == []


def test_a_disabled_camera_is_excluded(cafe, monkeypatch):
    make_camera(cafe, is_enabled=False)
    monkeypatch.setattr("apps.display.live.get_latest_tracks", lambda camera_id: make_tracks(box(1)))
    assert get_public_live_tracks(cafe) == []


def test_a_camera_with_unknown_resolution_is_excluded(cafe, monkeypatch):
    """No resolution means no coordinate space to place a dot in -- same
    honest-disclosure principle as the zone editor (Phase 5)."""
    make_camera(cafe, resolution_width=None, resolution_height=None)
    monkeypatch.setattr("apps.display.live.get_latest_tracks", lambda camera_id: make_tracks(box(1)))
    assert get_public_live_tracks(cafe) == []


def test_a_camera_with_no_cached_tracks_still_appears_with_no_people(cafe, monkeypatch):
    camera = make_camera(cafe)
    monkeypatch.setattr("apps.display.live.get_latest_tracks", lambda camera_id: None)

    result = get_public_live_tracks(cafe)
    assert len(result) == 1
    assert result[0]["camera_id"] == str(camera.id)
    assert result[0]["people"] == []


def test_position_is_the_box_centre(cafe, monkeypatch):
    make_camera(cafe)
    monkeypatch.setattr(
        "apps.display.live.get_latest_tracks",
        lambda camera_id: make_tracks(box(1, x1=100.0, y1=100.0, x2=200.0, y2=300.0)),
    )

    person = get_public_live_tracks(cafe)[0]["people"][0]
    assert person["x"] == 150.0
    assert person["y"] == 200.0


def test_a_track_with_no_active_session_is_fresh_coloured(cafe, monkeypatch):
    make_camera(cafe)
    monkeypatch.setattr("apps.display.live.get_latest_tracks", lambda camera_id: make_tracks(box(7)))

    person = get_public_live_tracks(cafe)[0]["people"][0]
    assert person["entry_at"] is None
    assert person["color"] == cafe.stay_color_stops[0]["color"]


def test_a_track_with_an_active_session_is_coloured_by_its_duration(cafe, monkeypatch):
    cafe.stay_color_stops = [{"seconds": 0, "color": "#0000ff"}, {"seconds": 60, "color": "#ff0000"}]
    cafe.save(update_fields=["stay_color_stops"])
    camera = make_camera(cafe)
    entry_at = timezone.now() - timedelta(seconds=60)
    make_session(cafe, camera_id=camera.id, track_id=7, entry_at=entry_at)
    monkeypatch.setattr("apps.display.live.get_latest_tracks", lambda camera_id: make_tracks(box(7)))

    person = get_public_live_tracks(cafe)[0]["people"][0]
    assert person["entry_at"] is not None
    assert person["color"] == "#ff0000"


def test_a_session_on_a_different_camera_is_not_matched(cafe, monkeypatch):
    """track_id is only unique per camera -- a session for track 7 on a
    *different* camera must not colour track 7 here."""
    make_camera(cafe, name="Entrance")
    make_session(cafe, camera_id=uuid.uuid4(), track_id=7, entry_at=timezone.now() - timedelta(minutes=30))
    monkeypatch.setattr("apps.display.live.get_latest_tracks", lambda camera_id: make_tracks(box(7)))

    person = get_public_live_tracks(cafe)[0]["people"][0]
    assert person["entry_at"] is None


def test_an_ended_session_does_not_colour_a_reused_track_id(cafe, monkeypatch):
    camera = make_camera(cafe)
    make_session(
        cafe, camera_id=camera.id, track_id=7, status=CustomerSession.Status.ENDED,
        entry_at=timezone.now() - timedelta(hours=2), exit_at=timezone.now() - timedelta(hours=1),
    )
    monkeypatch.setattr("apps.display.live.get_latest_tracks", lambda camera_id: make_tracks(box(7)))

    person = get_public_live_tracks(cafe)[0]["people"][0]
    assert person["entry_at"] is None


def test_a_redis_outage_degrades_to_an_empty_overlay_instead_of_raising(cafe, monkeypatch):
    """A public, unauthenticated page must never 500 on a transient Redis
    restart -- and on the WebSocket, an unhandled exception here would kill
    the loop that is supposed to keep the display live."""
    make_camera(cafe)

    def boom(camera_id):
        raise redis.ConnectionError("Error 11001 connecting to redis:6379.")

    monkeypatch.setattr("apps.display.live.get_latest_tracks", boom)

    result = get_public_live_tracks(cafe)
    assert len(result) == 1
    assert result[0]["people"] == []


def test_tracks_are_only_read_for_the_requested_cafes_cameras(cafe, other_cafe, monkeypatch):
    make_camera(other_cafe, name="Theirs")
    monkeypatch.setattr("apps.display.live.get_latest_tracks", lambda camera_id: make_tracks(box(1)))
    assert get_public_live_tracks(cafe) == []


# --------------------------------------------------------------------------- #
# get_public_stats
# --------------------------------------------------------------------------- #
def test_occupancy_counts_active_sessions_regardless_of_entry_day(cafe):
    make_session(cafe, entry_at=timezone.now() - timedelta(days=2))
    stats = get_public_stats(cafe)
    assert stats["occupancy"] == 1


def test_visitors_today_excludes_a_session_from_before_local_midnight(cafe):
    cafe.timezone = "UTC"
    cafe.save(update_fields=["timezone"])
    tz = zoneinfo.ZoneInfo("UTC")
    local_midnight = timezone.now().astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)

    make_session(cafe, entry_at=local_midnight - timedelta(minutes=1))  # yesterday, locally
    make_session(cafe, entry_at=local_midnight + timedelta(minutes=1))  # today, locally

    assert get_public_stats(cafe)["visitors_today"] == 1


def test_seating_capacity_is_included_for_computing_a_percentage(cafe):
    cafe.seating_capacity = 42
    cafe.save(update_fields=["seating_capacity"])
    assert get_public_stats(cafe)["seating_capacity"] == 42


def test_average_stay_seconds_is_none_with_no_ended_sessions_today(cafe):
    make_session(cafe)  # still active
    assert get_public_stats(cafe)["average_stay_seconds"] is None


def test_average_stay_seconds_averages_only_ended_sessions(cafe):
    now = timezone.now()
    make_session(
        cafe, track_id=1, status=CustomerSession.Status.ENDED,
        entry_at=now - timedelta(minutes=10), exit_at=now - timedelta(minutes=5),  # 300s
    )
    make_session(
        cafe, track_id=2, status=CustomerSession.Status.ENDED,
        entry_at=now - timedelta(minutes=20), exit_at=now - timedelta(minutes=10),  # 600s
    )
    assert get_public_stats(cafe)["average_stay_seconds"] == pytest.approx(450, abs=1)


def test_leaderboard_is_durations_only_sorted_descending(cafe):
    now = timezone.now()
    make_session(
        cafe, track_id=1, status=CustomerSession.Status.ENDED,
        entry_at=now - timedelta(minutes=10), exit_at=now - timedelta(minutes=9),  # 60s
    )
    make_session(cafe, track_id=2, entry_at=now - timedelta(minutes=30))  # active, ~1800s

    leaderboard = get_public_stats(cafe)["leaderboard_seconds"]
    assert leaderboard[0] == pytest.approx(1800, abs=2)
    assert leaderboard[1] == pytest.approx(60, abs=1)
    # Duration-only: no track_id, camera_id, or any identifying field present.
    assert all(isinstance(v, float) for v in leaderboard)


def test_leaderboard_is_capped_at_five(cafe):
    now = timezone.now()
    for i in range(8):
        make_session(cafe, track_id=i, entry_at=now - timedelta(minutes=i + 1))
    assert len(get_public_stats(cafe)["leaderboard_seconds"]) == 5


def test_stats_are_scoped_to_the_requested_cafe(cafe, other_cafe):
    make_session(other_cafe)
    stats = get_public_stats(cafe)
    assert stats["occupancy"] == 0
    assert stats["visitors_today"] == 0
