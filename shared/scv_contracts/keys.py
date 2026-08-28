"""Redis key names shared by the worker and the backend.

Centralised so a rename cannot leave one side writing to a key the other never
reads -- a failure mode that looks exactly like "the AI just stopped working".
"""
from __future__ import annotations

WORKER_HEARTBEAT = "scv:worker:{worker_id}:heartbeat"
CAMERA_STATE = "scv:camera:{camera_id}:state"
CAMERA_LATEST_FRAME = "scv:camera:{camera_id}:frame"
# Latest detection summary (person count, boxes, inference time). Ephemeral
# and short-TTL like the frame cache, not the durable event bus: it exists for
# a live "what does this camera see right now" view, not for analytics -- the
# periodic camera_stats event is what analytics is derived from.
CAMERA_LATEST_DETECTIONS = "scv:camera:{camera_id}:detections"
# Latest tracked boxes (anonymous track id + box + confidence). Same ephemeral
# reasoning as CAMERA_LATEST_DETECTIONS, and deliberately a separate key from
# it rather than folded into the same payload: detections and tracks are not
# index-aligned lists (tracking drops unconfirmed detections and can carry a
# recently-occluded track forward with no matching detection this tick), so
# giving each its own key keeps that distinction obvious to whatever reads them
# rather than implying a correspondence that is not real.
CAMERA_LATEST_TRACKS = "scv:camera:{camera_id}:tracks"


def worker_heartbeat_key(worker_id: str) -> str:
    return WORKER_HEARTBEAT.format(worker_id=worker_id)


def camera_state_key(camera_id: str) -> str:
    return CAMERA_STATE.format(camera_id=camera_id)


def camera_frame_key(camera_id: str) -> str:
    return CAMERA_LATEST_FRAME.format(camera_id=camera_id)


def camera_detections_key(camera_id: str) -> str:
    return CAMERA_LATEST_DETECTIONS.format(camera_id=camera_id)


def camera_tracks_key(camera_id: str) -> str:
    return CAMERA_LATEST_TRACKS.format(camera_id=camera_id)
