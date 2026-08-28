"""Worker lifecycle."""
from __future__ import annotations

import threading
import time

from scv_contracts import EventType
from worker.manager import CameraManager
from worker.runner import WorkerRunner


def offline_camera_manager(cfg, publisher) -> CameraManager:
    """A CameraManager whose fetch never touches the network.

    Runner tests exercise the heartbeat/lifecycle logic, not camera capture;
    without this, the manager's default fetcher would make a real HTTP call to
    the configured backend_url on every poll, making the test dependent on
    whatever happens to be listening on that port on the machine running it.
    """
    return CameraManager(cfg, publisher, fetch_camera_configs=lambda: [])


def test_worker_refuses_to_start_without_a_cafe_id(make_config, make_publisher):
    """Events for an unknown café are dropped by the backend, so fail early."""
    publisher = make_publisher()
    cfg = make_config(cafe_id="")
    runner = WorkerRunner(cfg, publisher=publisher, camera_manager=offline_camera_manager(cfg, publisher))

    assert runner.run() == 2
    assert publisher.events == []


def test_worker_announces_start_and_stop(make_config, make_publisher):
    publisher = make_publisher()
    cfg = make_config()
    runner = WorkerRunner(cfg, publisher=publisher, camera_manager=offline_camera_manager(cfg, publisher))

    thread = threading.Thread(target=runner.run)
    thread.start()
    time.sleep(0.5)
    runner._running = False
    thread.join(timeout=5)

    types = [str(event.type) for event in publisher.events]
    assert types[0] == EventType.WORKER_STARTED
    assert types[-1] == EventType.WORKER_STOPPED
    assert publisher.closed


def test_worker_reports_camera_capture_when_detection_is_off(make_config, make_publisher):
    """Honesty check: with no detector attached, the worker must not claim
    person_detection -- capabilities reflect what actually loaded, not what
    was requested in configuration."""
    publisher = make_publisher()
    cfg = make_config()
    manager = offline_camera_manager(cfg, publisher)  # no detector attached
    runner = WorkerRunner(cfg, publisher=publisher, camera_manager=manager)

    thread = threading.Thread(target=runner.run)
    thread.start()
    time.sleep(0.3)
    runner._running = False
    thread.join(timeout=5)

    started = publisher.events[0]
    assert started.payload["capabilities"] == ["camera_capture"]


def test_worker_reports_detection_and_tracking_when_a_detector_is_attached(make_config, make_publisher):
    """Tracking has no independent toggle -- it rides along with detection,
    so both capabilities appear together or not at all."""
    from worker.detector import PersonDetector

    publisher = make_publisher()
    cfg = make_config()
    fake_model = type("FakeModel", (), {"predict": lambda self, *a, **k: []})()
    detector = PersonDetector(fake_model, device="cpu", confidence_threshold=0.5)
    manager = CameraManager(cfg, publisher, fetch_camera_configs=lambda: [], detector=detector)
    runner = WorkerRunner(cfg, publisher=publisher, camera_manager=manager)

    thread = threading.Thread(target=runner.run)
    thread.start()
    time.sleep(0.3)
    runner._running = False
    thread.join(timeout=5)

    started = publisher.events[0]
    assert started.payload["capabilities"] == [
        "camera_capture", "person_detection", "multi_object_tracking",
    ]


def test_heartbeat_ttl_outlives_the_interval(make_config, make_publisher):
    """Otherwise the dashboard flaps between online and offline on a slow tick."""
    publisher = make_publisher()
    cfg = make_config(heartbeat_interval_seconds=2.0)
    runner = WorkerRunner(cfg, publisher=publisher, camera_manager=offline_camera_manager(cfg, publisher))

    thread = threading.Thread(target=runner.run)
    thread.start()
    time.sleep(0.4)
    runner._running = False
    thread.join(timeout=5)

    worker_id, ttl = publisher.heartbeats[0]
    assert worker_id == "worker-test"
    assert ttl >= 4


def test_camera_manager_is_started_and_stopped_with_the_worker(make_config, make_publisher):
    publisher = make_publisher()
    cfg = make_config()
    manager = offline_camera_manager(cfg, publisher)
    runner = WorkerRunner(cfg, publisher=publisher, camera_manager=manager)

    thread = threading.Thread(target=runner.run)
    thread.start()
    time.sleep(0.3)
    assert manager._thread is not None and manager._thread.is_alive()  # noqa: SLF001

    runner._running = False
    thread.join(timeout=5)

    assert manager._thread.is_alive() is False  # noqa: SLF001


def test_a_default_camera_manager_is_built_lazily_not_at_construction(make_config, make_publisher):
    """Building the default manager loads a YOLO model -- slow, one-time I/O
    that must not happen just from constructing a WorkerRunner."""
    runner = WorkerRunner(make_config(cafe_id=""), publisher=make_publisher())
    assert runner.camera_manager is None
