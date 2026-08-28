"""apps/cameras/streaming.py against fake Redis clients -- no real camera or
worker needed to prove the multipart framing and change-detection are correct.
"""
from __future__ import annotations

from apps.cameras.streaming import MJPEG_BOUNDARY, mjpeg_frames


class FakeRedis:
    """Always returns whatever was last set, like real Redis GET."""

    def __init__(self) -> None:
        self._values: dict[str, bytes] = {}

    def set_frame(self, camera_id: str, data: bytes) -> None:
        from scv_contracts.keys import camera_frame_key

        self._values[camera_frame_key(camera_id)] = data

    def get(self, key: str) -> bytes | None:
        return self._values.get(key)


class SequenceRedis:
    """Returns one value per call from a fixed script, and counts calls.

    Used to prove the generator polls silently through duplicate frames
    without yielding, rather than relying on real timing to observe it.
    """

    def __init__(self, values: list[bytes | None]) -> None:
        self._values = list(values)
        self.calls = 0

    def get(self, key: str) -> bytes | None:
        self.calls += 1
        if self._values:
            return self._values.pop(0)
        return None


def test_mjpeg_frames_emits_a_well_formed_multipart_part(monkeypatch):
    fake = FakeRedis()
    fake.set_frame("cam-1", b"\xff\xd8\xff\xe0firstframe")
    monkeypatch.setattr("apps.cameras.streaming.get_redis", lambda: fake)
    monkeypatch.setattr("apps.cameras.streaming.POLL_INTERVAL_SECONDS", 0)

    part = next(mjpeg_frames("cam-1"))

    assert part.startswith(f"--{MJPEG_BOUNDARY}\r\n".encode())
    assert b"Content-Type: image/jpeg\r\n" in part
    assert b"\xff\xd8\xff\xe0firstframe" in part


def test_mjpeg_frames_polls_through_duplicates_without_yielding(monkeypatch):
    """Otherwise a stalled camera would flood the connection with duplicate
    frames rather than the viewer simply seeing a frozen image, which is the
    honest representation of a stalled stream."""
    script = SequenceRedis([b"frame-a", b"frame-a", b"frame-a", b"frame-b"])
    monkeypatch.setattr("apps.cameras.streaming.get_redis", lambda: script)
    monkeypatch.setattr("apps.cameras.streaming.POLL_INTERVAL_SECONDS", 0)

    generator = mjpeg_frames("cam-1")
    first = next(generator)  # consumes 1 value: frame-a (new, yields)
    second = next(generator)  # consumes 3 values: a, a (skipped), then b (yields)

    assert b"frame-a" in first
    assert b"frame-b" in second
    assert script.calls == 4


def test_mjpeg_frames_skips_gracefully_when_no_frame_is_cached_yet(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("apps.cameras.streaming.get_redis", lambda: fake)
    monkeypatch.setattr("apps.cameras.streaming.POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr("apps.cameras.streaming.MAX_STREAM_SECONDS", 0.05)

    # Never publishes a frame; the generator must end on its own via the max
    # stream duration rather than looping forever.
    frames = list(mjpeg_frames("cam-1"))
    assert frames == []
