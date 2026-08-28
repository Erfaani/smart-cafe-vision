"""Shared test helpers for the AI worker suite, exposed as pytest fixtures.

Fixtures, not `from tests.helpers import ...`: `ultralytics` installs its own
top-level `tests` package into site-packages (its own test suite, shipped
alongside the library), which shadows any local `tests.<module>` absolute
import the moment ultralytics is installed -- this project hit exactly that
collision once torch/ultralytics arrived in Phase 3. Pytest's fixture
discovery goes through conftest.py directly, never through `sys.path`-based
package import, so it is unaffected by the name clash.
"""
from __future__ import annotations

import pytest

from worker.config import WorkerConfig


class RecordingPublisher:
    """A fake EventPublisher that records what it was asked to do.

    Used everywhere a test needs to observe worker behaviour without touching
    real Redis.
    """

    def __init__(self) -> None:
        self.events: list = []
        self.heartbeats: list[tuple[str, int]] = []
        self.buffered_count = 0
        self.closed = False

    def publish(self, event):
        self.events.append(event)
        return True

    def heartbeat(self, worker_id: str, ttl_seconds: int = 60):
        self.heartbeats.append((worker_id, ttl_seconds))
        return True

    def close(self):
        self.closed = True


def _build_config(**overrides) -> WorkerConfig:
    defaults = {
        "worker_id": "worker-test",
        "redis_url": "redis://localhost:6379/0",
        "stream_key": "test:events",
        "stream_maxlen": 100,
        "cafe_id": "8f0d2b1e-0000-4000-8000-000000000001",
        "device": "cpu",
        "model": "yolo11n.pt",
        "target_fps": 10.0,
        "heartbeat_interval_seconds": 1.0,
        "backend_url": "http://127.0.0.1:8000",
        "worker_token": "test-worker-token",
        "camera_poll_interval_seconds": 15.0,
        "camera_open_timeout_seconds": 10.0,
        "camera_stall_timeout_seconds": 15.0,
        "preview_publish_interval_seconds": 0.5,
        "preview_jpeg_quality": 70,
        "stats_publish_interval_seconds": 10.0,
        "detection_enabled": True,
        "confidence_threshold": 0.5,
        "models_dir": "",
        "tracker_type": "bytetrack",
    }
    defaults.update(overrides)
    return WorkerConfig(**defaults)


@pytest.fixture
def make_config():
    """A factory: `make_config(cafe_id="")` etc. Not a fixed WorkerConfig,
    since nearly every test needs its own overrides."""
    return _build_config


@pytest.fixture
def make_publisher():
    """A factory for fresh RecordingPublisher instances."""
    return RecordingPublisher
