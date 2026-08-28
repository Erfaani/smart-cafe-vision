"""Live preview, sourced from the frame the AI worker last cached in Redis.

Why this shape, rather than the browser talking to the AI worker directly: the
browser never talks to anything but this backend (see docs/architecture.md,
"tokens live in httpOnly cookies") -- exposing the worker's port would mean a
second thing on the LAN that needs its own auth story, and would leak the
worker's network location into the frontend. Routing the frame through Redis
instead means the worker needs no inbound port at all.

This is a preview, not the detection feed: the worker publishes a frame here at
a low, fixed rate (worker/capture.py), decoupled from both the camera's native
FPS and the AI inference rate (spec §22 -- these three numbers are allowed to
differ, and conflating them is exactly the bug this project has repeatedly
guarded against).
"""
from __future__ import annotations

import time
from collections.abc import Iterator

from apps.events.bus import get_redis
from scv_contracts.keys import camera_frame_key

MJPEG_BOUNDARY = "smartcafevisionframe"
#: How often to poll Redis for a new frame while a preview connection is open.
#: Faster than this outruns the worker's own publish rate for no benefit.
POLL_INTERVAL_SECONDS = 0.2
#: A preview tab left open must not hold a backend thread forever.
MAX_STREAM_SECONDS = 600


def get_latest_frame(camera_id: str) -> bytes | None:
    """The most recent JPEG the worker cached for this camera, if any and if
    still fresh (the key carries its own TTL, set by the publisher)."""
    client = get_redis()
    return client.get(camera_frame_key(camera_id))


def mjpeg_frames(camera_id: str) -> Iterator[bytes]:
    """Yield multipart/x-mixed-replace parts, one per new frame observed.

    A plain blocking loop with a sleep: Django's sync views (this one included)
    run in ASGI's sync-to-async thread pool, so blocking here costs one worker
    thread for the connection's lifetime and nothing else. That is an
    acceptable trade for the handful of concurrent previews a café dashboard
    opens -- not a design meant to scale to hundreds of simultaneous viewers.
    """
    client = get_redis()
    key = camera_frame_key(camera_id)
    last_frame: bytes | None = None
    started = time.monotonic()

    while time.monotonic() - started < MAX_STREAM_SECONDS:
        frame = client.get(key)
        if frame and frame != last_frame:
            last_frame = frame
            yield (
                f"--{MJPEG_BOUNDARY}\r\n"
                f"Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(frame)}\r\n\r\n"
            ).encode() + frame + b"\r\n"
        time.sleep(POLL_INTERVAL_SECONDS)
