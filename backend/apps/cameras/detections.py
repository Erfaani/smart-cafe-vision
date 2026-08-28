"""Live detection summary, sourced from Redis (see streaming.py for why
Redis, not a direct worker connection).

Deliberately separate from the durable event log: a detection tick happens
several times a second per camera, and persisting each one as a TrackingEvent
row would flood the audit log with data nothing needs historically. What is
worth persisting -- a periodic snapshot, at the same cadence as camera_stats
-- already lands on Camera.last_person_count via apps/cameras/projections.py.
This module is for "what does this camera see right now", read straight from
the cache the worker refreshes on every detection tick.
"""
from __future__ import annotations

import json
from typing import Any

from apps.events.bus import get_redis
from scv_contracts.keys import camera_detections_key, camera_tracks_key


def get_latest_detections(camera_id: str) -> dict[str, Any] | None:
    """The most recent detection summary for this camera, if any and if still
    fresh (the key carries its own TTL, set by the worker)."""
    client = get_redis()
    raw = client.get(camera_detections_key(camera_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def get_latest_tracks(camera_id: str) -> dict[str, Any] | None:
    """The most recent tracked-box summary for this camera (Phase 4),
    anonymous track id included -- same cache/TTL reasoning as
    get_latest_detections, and deliberately a separate Redis key from it
    rather than folded into the same payload: see CAMERA_LATEST_TRACKS in
    scv_contracts.keys for why detections and tracks are not index-aligned
    lists."""
    client = get_redis()
    raw = client.get(camera_tracks_key(camera_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
