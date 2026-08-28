"""CameraManager reconciliation logic against fake capture workers and a fake
backend fetcher -- no real threads doing RTSP, no real HTTP call.
"""
from __future__ import annotations

import time

from worker.capture import CameraConfig
from worker.manager import CameraManager


class FakeCaptureWorker:
    """Records start/stop calls instead of doing anything real."""

    instances: list[FakeCaptureWorker] = []

    def __init__(self, camera: CameraConfig) -> None:
        self.camera = camera
        self.started = False
        self.stopped = False
        FakeCaptureWorker.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def camera(
    id_="cam-1", name="Entrance", url="rtsp://192.168.1.64/live", transport="tcp", zones=(), tables=(),
) -> CameraConfig:
    return CameraConfig(
        id=id_, name=name, url=url, transport=transport, zones=tuple(zones), tables=tuple(tables),
    )


def make_manager(make_config, make_publisher, fetch_sequence=None):
    FakeCaptureWorker.instances = []
    calls = {"fetch_count": 0}
    sequence = list(fetch_sequence or [[]])

    def fetch():
        calls["fetch_count"] += 1
        # Once the script is exhausted, keep returning the last entry so a
        # manager left running past the scripted polls behaves predictably.
        return sequence[min(calls["fetch_count"] - 1, len(sequence) - 1)]

    manager = CameraManager(
        make_config(),
        make_publisher(),
        fetch_camera_configs=fetch,
        capture_worker_factory=lambda cam: FakeCaptureWorker(cam),
        redis_client=object(),  # never touched: the fake factory bypasses _make_frame_publisher
    )
    return manager, calls


# --------------------------------------------------------------------------- #
# reconciliation
# --------------------------------------------------------------------------- #
def test_poll_once_starts_a_worker_for_each_configured_camera(make_config, make_publisher):
    manager, _ = make_manager(make_config, make_publisher, [[camera("cam-1"), camera("cam-2")]])
    manager.poll_once()

    assert manager.active_camera_ids == {"cam-1", "cam-2"}
    assert all(instance.started for instance in FakeCaptureWorker.instances)


def test_a_camera_removed_from_the_list_is_stopped(make_config, make_publisher):
    manager, _ = make_manager(
        make_config, make_publisher, [[camera("cam-1"), camera("cam-2")], [camera("cam-1")]]
    )
    manager.poll_once()
    manager.poll_once()

    assert manager.active_camera_ids == {"cam-1"}
    removed = next(i for i in FakeCaptureWorker.instances if i.camera.id == "cam-2")
    assert removed.stopped is True


def test_an_unchanged_camera_keeps_the_same_worker_instance(make_config, make_publisher):
    """Restarting on every poll would drop the connection for no reason."""
    manager, _ = make_manager(make_config, make_publisher, [[camera("cam-1")], [camera("cam-1")]])
    manager.poll_once()
    first_instance = manager._workers["cam-1"]  # noqa: SLF001 - white-box check
    manager.poll_once()
    second_instance = manager._workers["cam-1"]  # noqa: SLF001

    assert first_instance is second_instance
    assert first_instance.stopped is False
    assert len(FakeCaptureWorker.instances) == 1


def test_an_edited_camera_restarts_with_a_new_worker(make_config, make_publisher):
    manager, _ = make_manager(
        make_config,
        make_publisher,
        [
            [camera("cam-1", url="rtsp://192.168.1.64/live")],
            [camera("cam-1", url="rtsp://192.168.1.99/live")],  # IP changed
        ],
    )
    manager.poll_once()
    old_instance = manager._workers["cam-1"]  # noqa: SLF001
    manager.poll_once()
    new_instance = manager._workers["cam-1"]  # noqa: SLF001

    assert old_instance is not new_instance
    assert old_instance.stopped is True
    assert new_instance.started is True


def test_a_transport_change_also_counts_as_a_reconfiguration(make_config, make_publisher):
    manager, _ = make_manager(
        make_config, make_publisher, [[camera("cam-1", transport="tcp")], [camera("cam-1", transport="udp")]]
    )
    manager.poll_once()
    old_instance = manager._workers["cam-1"]  # noqa: SLF001
    manager.poll_once()

    assert old_instance.stopped is True


def test_a_failed_fetch_leaves_running_cameras_untouched(make_config, make_publisher):
    """The backend being briefly unreachable must not tear down a live capture."""
    manager, calls = make_manager(make_config, make_publisher, [[camera("cam-1")], None, None])
    manager.poll_once()
    manager.poll_once()
    manager.poll_once()

    assert manager.active_camera_ids == {"cam-1"}
    assert calls["fetch_count"] == 3
    # Exactly one worker was ever created -- the None responses triggered no
    # start/stop churn at all.
    assert len(FakeCaptureWorker.instances) == 1
    assert FakeCaptureWorker.instances[0].stopped is False


def test_an_empty_camera_list_stops_everything(make_config, make_publisher):
    """Distinct from a failed fetch: an explicit empty list means the café
    genuinely has no enabled cameras right now, and must be honoured."""
    manager, _ = make_manager(make_config, make_publisher, [[camera("cam-1")], []])
    manager.poll_once()
    manager.poll_once()

    assert manager.active_camera_ids == set()
    assert FakeCaptureWorker.instances[0].stopped is True


# --------------------------------------------------------------------------- #
# lifecycle
# --------------------------------------------------------------------------- #
def test_start_reconciles_immediately_without_waiting_for_the_poll_interval(make_config, make_publisher):
    manager, _ = make_manager(make_config, make_publisher, [[camera("cam-1")]])
    manager._config = make_config(camera_poll_interval_seconds=60)  # would never fire in the test window

    manager.start()
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not manager.active_camera_ids:
            time.sleep(0.01)
        assert manager.active_camera_ids == {"cam-1"}
    finally:
        manager.stop()


def test_stop_stops_every_active_worker(make_config, make_publisher):
    manager, _ = make_manager(make_config, make_publisher, [[camera("cam-1"), camera("cam-2")]])
    manager.poll_once()

    manager.stop()

    assert all(instance.stopped for instance in FakeCaptureWorker.instances)
    assert manager.active_camera_ids == set()


def test_stop_is_safe_to_call_before_start(make_config, make_publisher):
    manager, _ = make_manager(make_config, make_publisher, [[]])
    manager.stop()  # must not raise


# --------------------------------------------------------------------------- #
# the default HTTP fetcher, against a fake requests-like server
# --------------------------------------------------------------------------- #
def test_default_fetcher_parses_a_successful_response(monkeypatch):
    from worker.manager import fetch_camera_configs_from_backend

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"id": "cam-1", "name": "Entrance", "url": "rtsp://x/live", "transport": "tcp"}]

    captured = {}

    def fake_get(url, params, headers, timeout):
        captured.update(url=url, params=params, headers=headers, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr("worker.manager.requests.get", fake_get)

    result = fetch_camera_configs_from_backend("http://backend:8000", "secret-token", "cafe-1")

    assert result == [CameraConfig(id="cam-1", name="Entrance", url="rtsp://x/live", transport="tcp")]
    assert captured["headers"]["X-Worker-Token"] == "secret-token"
    assert captured["params"]["cafe_id"] == "cafe-1"


def test_default_fetcher_returns_none_on_a_network_error(monkeypatch):
    import requests

    from worker.manager import fetch_camera_configs_from_backend

    def fake_get(*args, **kwargs):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr("worker.manager.requests.get", fake_get)

    assert fetch_camera_configs_from_backend("http://backend:8000", "token", "cafe-1") is None


def test_default_fetcher_returns_none_on_a_malformed_payload(monkeypatch):
    from worker.manager import fetch_camera_configs_from_backend

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"id": "cam-1"}]  # missing name/url/transport

    monkeypatch.setattr("worker.manager.requests.get", lambda *a, **k: FakeResponse())

    assert fetch_camera_configs_from_backend("http://backend:8000", "token", "cafe-1") is None


# --------------------------------------------------------------------------- #
# per-camera tracker isolation (Phase 4) -- the default factory, not the
# fake capture_worker_factory the tests above use, since tracker construction
# happens inside _default_capture_worker_factory itself. Workers are built but
# deliberately never started: starting one spins up a real thread that tries
# to open an actual RTSP connection via cv2, which these tests have no need
# to touch at all -- only the constructed CameraCaptureWorker's attributes.
# --------------------------------------------------------------------------- #
def make_fake_detector():
    from worker.detector import PersonDetector

    fake_model = type("FakeModel", (), {"predict": lambda self, *a, **k: []})()
    return PersonDetector(fake_model, device="cpu", confidence_threshold=0.5)


def test_each_camera_gets_its_own_tracker_instance(make_config, make_publisher):
    manager = CameraManager(
        make_config(),
        make_publisher(),
        fetch_camera_configs=lambda: [],
        detector=make_fake_detector(),
    )

    worker_a = manager._default_capture_worker_factory(camera("cam-a"))  # noqa: SLF001
    worker_b = manager._default_capture_worker_factory(camera("cam-b"))  # noqa: SLF001

    assert worker_a._tracker is not None  # noqa: SLF001
    assert worker_b._tracker is not None  # noqa: SLF001
    assert worker_a._tracker is not worker_b._tracker  # noqa: SLF001


def test_no_tracker_is_built_without_a_detector(make_config, make_publisher):
    """Nothing for a tracker to associate without detections feeding it --
    capture-only mode stays capture-only, not "capture plus an idle tracker"."""
    manager = CameraManager(
        make_config(), make_publisher(), fetch_camera_configs=lambda: []
    )  # no detector

    worker = manager._default_capture_worker_factory(camera())  # noqa: SLF001

    assert worker._tracker is None  # noqa: SLF001


def test_a_tracker_construction_failure_falls_back_to_no_tracking(make_config, make_publisher, monkeypatch):
    """Mirrors build_detector's own graceful degradation: a tracker that
    cannot be built must not prevent the camera from capturing."""
    manager = CameraManager(
        make_config(),
        make_publisher(),
        fetch_camera_configs=lambda: [],
        detector=make_fake_detector(),
    )

    def explode(tracker_type):
        raise RuntimeError("tracker exploded")

    monkeypatch.setattr("worker.manager.PersonTracker", explode)

    worker = manager._default_capture_worker_factory(camera())  # noqa: SLF001

    assert worker._tracker is None  # noqa: SLF001


def test_the_configured_tracker_type_is_used(make_config, make_publisher, monkeypatch):
    captured = {}

    class RecordingTracker:
        def __init__(self, tracker_type):
            captured["tracker_type"] = tracker_type

    monkeypatch.setattr("worker.manager.PersonTracker", RecordingTracker)

    manager = CameraManager(
        make_config(tracker_type="botsort"),
        make_publisher(),
        fetch_camera_configs=lambda: [],
        detector=make_fake_detector(),
    )
    manager._default_capture_worker_factory(camera())  # noqa: SLF001

    assert captured["tracker_type"] == "botsort"


# --------------------------------------------------------------------------- #
# per-camera zone detector wiring (Phase 5)
# --------------------------------------------------------------------------- #
def make_zone():
    from worker.zones import ZoneConfig

    return ZoneConfig(id="z1", name="Front door", point_a=(100, 0), point_b=(100, 200))


def test_a_camera_with_zones_gets_a_zone_detector(make_config, make_publisher):
    manager = CameraManager(
        make_config(), make_publisher(), fetch_camera_configs=lambda: [], detector=make_fake_detector()
    )

    worker = manager._default_capture_worker_factory(camera(zones=[make_zone()]))  # noqa: SLF001

    assert worker._zone_detector is not None  # noqa: SLF001


def test_a_camera_with_no_zones_gets_no_zone_detector(make_config, make_publisher):
    """Nothing configured, nothing to check -- matches the same "no work,
    no component" principle as capture-only mode having no tracker."""
    manager = CameraManager(
        make_config(), make_publisher(), fetch_camera_configs=lambda: [], detector=make_fake_detector()
    )

    worker = manager._default_capture_worker_factory(camera(zones=()))  # noqa: SLF001

    assert worker._zone_detector is None  # noqa: SLF001


def test_no_zone_detector_is_built_without_a_detector(make_config, make_publisher):
    """Zone crossing needs track ids, which need a tracker, which needs a
    detector -- capture-only mode has none of the chain."""
    manager = CameraManager(
        make_config(), make_publisher(), fetch_camera_configs=lambda: []
    )  # no detector

    worker = manager._default_capture_worker_factory(camera(zones=[make_zone()]))  # noqa: SLF001

    assert worker._zone_detector is None  # noqa: SLF001


def test_each_camera_gets_its_own_zone_detector_instance(make_config, make_publisher):
    manager = CameraManager(
        make_config(), make_publisher(), fetch_camera_configs=lambda: [], detector=make_fake_detector()
    )

    worker_a = manager._default_capture_worker_factory(camera("cam-a", zones=[make_zone()]))  # noqa: SLF001
    worker_b = manager._default_capture_worker_factory(camera("cam-b", zones=[make_zone()]))  # noqa: SLF001

    assert worker_a._zone_detector is not worker_b._zone_detector  # noqa: SLF001


def test_a_zone_detector_construction_failure_falls_back_to_no_crossing_detection(
    make_config, make_publisher, monkeypatch
):
    manager = CameraManager(
        make_config(), make_publisher(), fetch_camera_configs=lambda: [], detector=make_fake_detector()
    )

    def explode(zones):
        raise RuntimeError("zone detector exploded")

    monkeypatch.setattr("worker.manager.ZoneCrossingDetector", explode)

    worker = manager._default_capture_worker_factory(camera(zones=[make_zone()]))  # noqa: SLF001

    assert worker._zone_detector is None  # noqa: SLF001


# --------------------------------------------------------------------------- #
# fetching zones from the backend
# --------------------------------------------------------------------------- #
def test_default_fetcher_parses_zones(monkeypatch):
    from worker.manager import fetch_camera_configs_from_backend

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {
                    "id": "cam-1",
                    "name": "Entrance",
                    "url": "rtsp://x/live",
                    "transport": "tcp",
                    "zones": [
                        {
                            "id": "z1",
                            "name": "Front door",
                            "point_a": [100, 0],
                            "point_b": [100, 200],
                            "entry_is_positive_side": True,
                        }
                    ],
                }
            ]

    monkeypatch.setattr("worker.manager.requests.get", lambda *a, **k: FakeResponse())

    result = fetch_camera_configs_from_backend("http://backend:8000", "token", "cafe-1")

    assert len(result[0].zones) == 1
    zone = result[0].zones[0]
    assert zone.id == "z1"
    assert zone.name == "Front door"
    assert zone.point_a == (100, 0)
    assert zone.point_b == (100, 200)
    assert zone.entry_is_positive_side is True


def test_default_fetcher_treats_a_camera_with_no_zones_key_as_having_none(monkeypatch):
    """Backward compatible with a backend response that predates zones."""
    from worker.manager import fetch_camera_configs_from_backend

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"id": "cam-1", "name": "Entrance", "url": "rtsp://x/live", "transport": "tcp"}]

    monkeypatch.setattr("worker.manager.requests.get", lambda *a, **k: FakeResponse())

    result = fetch_camera_configs_from_backend("http://backend:8000", "token", "cafe-1")

    assert result[0].zones == ()


def test_default_fetcher_returns_none_when_a_zone_is_malformed(monkeypatch):
    from worker.manager import fetch_camera_configs_from_backend

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {
                    "id": "cam-1",
                    "name": "Entrance",
                    "url": "rtsp://x/live",
                    "transport": "tcp",
                    "zones": [{"id": "z1", "name": "Front door"}],  # missing point_a/point_b
                }
            ]

    monkeypatch.setattr("worker.manager.requests.get", lambda *a, **k: FakeResponse())

    assert fetch_camera_configs_from_backend("http://backend:8000", "token", "cafe-1") is None


# --------------------------------------------------------------------------- #
# per-camera table detector wiring (Phase 9)
# --------------------------------------------------------------------------- #
def make_table():
    from worker.tables import TableZoneConfig

    return TableZoneConfig(id="t1", name="Table 1", x1=0, y1=0, x2=100, y2=100)


def test_a_camera_with_tables_gets_a_table_detector(make_config, make_publisher):
    manager = CameraManager(
        make_config(), make_publisher(), fetch_camera_configs=lambda: [], detector=make_fake_detector()
    )

    worker = manager._default_capture_worker_factory(camera(tables=[make_table()]))  # noqa: SLF001

    assert worker._table_detector is not None  # noqa: SLF001


def test_a_camera_with_no_tables_gets_no_table_detector(make_config, make_publisher):
    manager = CameraManager(
        make_config(), make_publisher(), fetch_camera_configs=lambda: [], detector=make_fake_detector()
    )

    worker = manager._default_capture_worker_factory(camera(tables=()))  # noqa: SLF001

    assert worker._table_detector is None  # noqa: SLF001


def test_no_table_detector_is_built_without_a_detector(make_config, make_publisher):
    manager = CameraManager(
        make_config(), make_publisher(), fetch_camera_configs=lambda: []
    )  # no detector

    worker = manager._default_capture_worker_factory(camera(tables=[make_table()]))  # noqa: SLF001

    assert worker._table_detector is None  # noqa: SLF001


def test_each_camera_gets_its_own_table_detector_instance(make_config, make_publisher):
    manager = CameraManager(
        make_config(), make_publisher(), fetch_camera_configs=lambda: [], detector=make_fake_detector()
    )

    worker_a = manager._default_capture_worker_factory(camera("cam-a", tables=[make_table()]))  # noqa: SLF001
    worker_b = manager._default_capture_worker_factory(camera("cam-b", tables=[make_table()]))  # noqa: SLF001

    assert worker_a._table_detector is not worker_b._table_detector  # noqa: SLF001


def test_a_table_detector_construction_failure_falls_back_to_no_occupancy_detection(
    make_config, make_publisher, monkeypatch
):
    manager = CameraManager(
        make_config(), make_publisher(), fetch_camera_configs=lambda: [], detector=make_fake_detector()
    )

    def explode(tables):
        raise RuntimeError("table detector exploded")

    monkeypatch.setattr("worker.manager.TableOccupancyDetector", explode)

    worker = manager._default_capture_worker_factory(camera(tables=[make_table()]))  # noqa: SLF001

    assert worker._table_detector is None  # noqa: SLF001


# --------------------------------------------------------------------------- #
# fetching tables from the backend
# --------------------------------------------------------------------------- #
def test_default_fetcher_parses_tables(monkeypatch):
    from worker.manager import fetch_camera_configs_from_backend

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {
                    "id": "cam-1",
                    "name": "Entrance",
                    "url": "rtsp://x/live",
                    "transport": "tcp",
                    "tables": [{"id": "t1", "name": "Table 1", "x1": 0, "y1": 0, "x2": 100, "y2": 100}],
                }
            ]

    monkeypatch.setattr("worker.manager.requests.get", lambda *a, **k: FakeResponse())

    result = fetch_camera_configs_from_backend("http://backend:8000", "token", "cafe-1")

    assert len(result[0].tables) == 1
    table = result[0].tables[0]
    assert table.id == "t1"
    assert table.name == "Table 1"
    assert (table.x1, table.y1, table.x2, table.y2) == (0, 0, 100, 100)


def test_default_fetcher_treats_a_camera_with_no_tables_key_as_having_none(monkeypatch):
    """Backward compatible with a backend response that predates tables."""
    from worker.manager import fetch_camera_configs_from_backend

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"id": "cam-1", "name": "Entrance", "url": "rtsp://x/live", "transport": "tcp"}]

    monkeypatch.setattr("worker.manager.requests.get", lambda *a, **k: FakeResponse())

    result = fetch_camera_configs_from_backend("http://backend:8000", "token", "cafe-1")

    assert result[0].tables == ()


def test_default_fetcher_returns_none_when_a_table_is_malformed(monkeypatch):
    from worker.manager import fetch_camera_configs_from_backend

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {
                    "id": "cam-1",
                    "name": "Entrance",
                    "url": "rtsp://x/live",
                    "transport": "tcp",
                    "tables": [{"id": "t1", "name": "Table 1"}],  # missing x1/y1/x2/y2
                }
            ]

    monkeypatch.setattr("worker.manager.requests.get", lambda *a, **k: FakeResponse())

    assert fetch_camera_configs_from_backend("http://backend:8000", "token", "cafe-1") is None
