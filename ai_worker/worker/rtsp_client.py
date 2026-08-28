"""The only module in this package that imports cv2 directly.

Isolated so `worker/capture.py` -- where the actual reconnection and stall
logic lives -- can be tested against a fake `VideoSource` without OpenCV or a
real camera anywhere near the test. `Protocol` typing (not an ABC) so the fake
used in tests needs no inheritance relationship to this module at all.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

logger = logging.getLogger("scv.worker.rtsp")


class VideoSource(Protocol):
    def is_opened(self) -> bool: ...
    def read(self) -> tuple[bool, object]: ...
    def get_resolution(self) -> tuple[int, int]: ...
    def release(self) -> None: ...


class OpenCvRtspSource:
    """Real RTSP capture via OpenCV's FFmpeg backend."""

    def __init__(
        self, url: str, transport: str, open_timeout_seconds: float, read_timeout_seconds: float
    ) -> None:
        import cv2

        # OpenCV has no public API parameter to choose the RTSP transport (TCP
        # vs UDP); this environment variable is the documented way its FFmpeg
        # backend reads it. Undocumented in OpenCV's own API reference, well
        # documented in FFmpeg's -- worth this comment so it doesn't get
        # "cleaned up" as a stray os.environ write later.
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = f"rtsp_transport;{transport}"

        self._cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        # These map to FFmpeg's connection/read timeouts and make read() return
        # False on a stall instead of blocking forever. That matters because
        # Python cannot forcibly interrupt a blocked native call from another
        # thread -- a watchdog thread comparing timestamps could detect a
        # stall but never break out of it, so the timeout has to be set here,
        # at the source, to be real.
        self._cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, open_timeout_seconds * 1000)
        self._cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, read_timeout_seconds * 1000)

    def is_opened(self) -> bool:
        return bool(self._cap.isOpened())

    def read(self) -> tuple[bool, object]:
        return self._cap.read()

    def get_resolution(self) -> tuple[int, int]:
        import cv2

        width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return width, height

    def release(self) -> None:
        self._cap.release()


def default_source_factory(
    url: str, transport: str, open_timeout_seconds: float, read_timeout_seconds: float
) -> VideoSource:
    return OpenCvRtspSource(url, transport, open_timeout_seconds, read_timeout_seconds)


def default_jpeg_encoder(frame: object, quality: int) -> bytes | None:
    import cv2

    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buffer.tobytes() if ok else None
