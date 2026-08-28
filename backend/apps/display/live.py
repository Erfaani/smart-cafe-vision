"""Composition layer for the public display.

Turns the Redis live-tracks cache (apps/cameras/detections.py) and the
CustomerSession table (apps/sessions/models.py) into exactly what a kiosk
browser needs, in one place -- so neither apps.cameras nor apps.sessions
needs to know "there is a public display" as a concept.

Nothing here is stored: both functions are read-only compositions computed
fresh on every call, whether that call comes from the public HTTP endpoints
(apps/display/views.py) or the WebSocket's periodic push
(apps/display/consumers.py).
"""
from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime
from typing import Any

import redis
from django.utils import timezone

from apps.cameras.detections import get_latest_tracks
from apps.cameras.models import Camera
from apps.core.color import color_for_duration
from apps.sessions.models import CustomerSession
from apps.tenants.models import Cafe

logger = logging.getLogger("smartcafe.display")

LEADERBOARD_LIMIT = 5


def get_public_live_tracks(cafe: Cafe) -> list[dict[str, Any]]:
    """One entry per enabled camera with a known resolution, each carrying
    every currently tracked person's position.

    Position is the tracked box's centre, not worker/zones.py's bottom-centre
    reference point -- that convention exists for threshold-crossing
    precision, a different purpose from "where does a dot belong on screen."

    A track with no matching ACTIVE session -- not yet crossed a configured
    entry line, or the camera has no zone drawn on it at all -- still
    appears, coloured as fresh (`entry_at: null`). An empty overlay on a
    camera without a zone would read as broken rather than merely quiet, and
    a café's very first camera often has no zone yet.
    """
    cameras = (
        Camera.objects.filter(cafe=cafe, is_enabled=True)
        .exclude(resolution_width__isnull=True)
        .exclude(resolution_height__isnull=True)
    )
    if not cameras:
        return []

    active_entries = {
        (str(row["camera_id"]), row["track_id"]): row["entry_at"]
        for row in CustomerSession.objects.filter(
            cafe=cafe, status=CustomerSession.Status.ACTIVE
        ).values("camera_id", "track_id", "entry_at")
    }
    stops = cafe.stay_color_stops
    now = timezone.now()
    fresh_color = stops[0]["color"]

    result: list[dict[str, Any]] = []
    for camera in cameras:
        try:
            summary = get_latest_tracks(str(camera.id)) or {}
        except redis.RedisError:
            # A public, unauthenticated page must degrade, not 500: a
            # transient Redis restart (docs/architecture.md's own failure
            # table treats this as routine) should show an empty overlay for
            # this camera, not take down the whole display or -- worse, on
            # the WebSocket -- kill the loop that is supposed to keep it live.
            logger.warning("display_live_tracks_redis_unavailable camera=%s", camera.id)
            summary = {}
        people = []
        for box in summary.get("tracks", []):
            track_id = box.get("track_id")
            entry_at = active_entries.get((str(camera.id), track_id))
            color = (
                color_for_duration((now - entry_at).total_seconds(), stops)
                if entry_at is not None
                else fresh_color
            )
            people.append(
                {
                    "track_id": track_id,
                    "x": (box["x1"] + box["x2"]) / 2.0,
                    "y": (box["y1"] + box["y2"]) / 2.0,
                    "entry_at": entry_at.isoformat() if entry_at is not None else None,
                    "color": color,
                }
            )
        result.append(
            {
                "camera_id": str(camera.id),
                "camera_name": camera.name,
                "resolution_width": camera.resolution_width,
                "resolution_height": camera.resolution_height,
                "people": people,
            }
        )
    return result


def get_public_stats(cafe: Cafe) -> dict[str, Any]:
    """Occupancy and a duration-only leaderboard -- deliberately never a
    track id or a camera name in the leaderboard: "longest stay today: 1h
    42m" is a fun, anonymous number; "camera 2, track 47: 1h 42m" is
    something the room could use to single someone out. See
    apps/display/models.py's module docstring for the same principle applied
    to messages.
    """
    now = timezone.now()
    local_midnight = _local_midnight(cafe, now)

    active_qs = CustomerSession.objects.filter(cafe=cafe, status=CustomerSession.Status.ACTIVE)
    today_qs = CustomerSession.objects.filter(cafe=cafe, entry_at__gte=local_midnight)

    ended_durations = [
        (row["exit_at"] - row["entry_at"]).total_seconds()
        for row in today_qs.filter(
            status=CustomerSession.Status.ENDED, exit_at__isnull=False
        ).values("entry_at", "exit_at")
    ]
    active_durations_today = [
        (now - row["entry_at"]).total_seconds()
        for row in today_qs.filter(status=CustomerSession.Status.ACTIVE).values("entry_at")
    ]
    all_durations_today = ended_durations + active_durations_today

    return {
        "occupancy": active_qs.count(),
        "seating_capacity": cafe.seating_capacity,
        "visitors_today": today_qs.count(),
        "average_stay_seconds": (
            sum(ended_durations) / len(ended_durations) if ended_durations else None
        ),
        "leaderboard_seconds": sorted(all_durations_today, reverse=True)[:LEADERBOARD_LIMIT],
    }


def _local_midnight(cafe: Cafe, now: datetime) -> datetime:
    """Start of "today" in the café's own timezone (spec: analytics group by
    local day, not UTC day) -- `cafe.timezone` is already validated as a real
    IANA name at write time (CafeSerializer.validate_timezone), so this
    trusts it rather than re-checking."""
    tz = zoneinfo.ZoneInfo(cafe.timezone)
    return now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
