"""apps/cameras/detections.py against a fake Redis client -- no real worker or
detector needed to prove the cache read is correct."""
from __future__ import annotations

import json

from apps.cameras.detections import get_latest_detections


class FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, bytes] = {}

    def set_detections(self, camera_id: str, payload: dict) -> None:
        from scv_contracts.keys import camera_detections_key

        self._values[camera_detections_key(camera_id)] = json.dumps(payload).encode()

    def get(self, key: str) -> bytes | None:
        return self._values.get(key)


def test_returns_none_when_nothing_is_cached(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("apps.cameras.detections.get_redis", lambda: fake)
    assert get_latest_detections("cam-1") is None


def test_returns_the_decoded_summary(monkeypatch):
    fake = FakeRedis()
    fake.set_detections("cam-1", {"person_count": 2, "inference_ms": 30.0, "boxes": []})
    monkeypatch.setattr("apps.cameras.detections.get_redis", lambda: fake)

    result = get_latest_detections("cam-1")

    assert result == {"person_count": 2, "inference_ms": 30.0, "boxes": []}


def test_malformed_json_is_treated_as_absent_rather_than_raising(monkeypatch):
    fake = FakeRedis()
    fake._values["scv:camera:cam-1:detections"] = b"not-json"
    monkeypatch.setattr("apps.cameras.detections.get_redis", lambda: fake)

    assert get_latest_detections("cam-1") is None
