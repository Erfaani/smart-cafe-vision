"""CameraCaptureWorker against fake sources -- no OpenCV, no camera.

Every scenario here is a real failure mode a café camera exhibits: refusing
the connection, accepting it and then going silent, dropping mid-stream. The
one property under test throughout is that none of them ever leak the fake
source (release() always called) or block the worker thread indefinitely.
"""
from __future__ import annotations

import time

import pytest

from worker.capture import CameraCaptureWorker, CameraConfig


def make_camera(**overrides) -> CameraConfig:
    defaults = {"id": "cam-1", "name": "Entrance", "url": "rtsp://192.168.1.64/live", "transport": "tcp"}
    defaults.update(overrides)
    return CameraConfig(**defaults)


class FakeSource:
    """A scripted VideoSource: `reads` is a list of (ok, frame) results
    consumed one per call; after the list is exhausted, keeps returning the
    last entry. Records whether release() was called, so leak tests are exact.
    """

    def __init__(
        self,
        reads: list[tuple[bool, object]],
        *,
        opens: bool = True,
        resolution=(1280, 720),
        read_delay_seconds: float = 0.002,
    ):
        self.opens = opens
        self._reads = list(reads)
        self._resolution = resolution
        self._read_delay = read_delay_seconds
        self.released = False
        self.read_count = 0

    def is_opened(self) -> bool:
        return self.opens

    def read(self):
        # A tiny delay so a repeating "always succeeds" fixture behaves like a
        # real stream waiting on the network rather than a tight CPU spin.
        time.sleep(self._read_delay)
        self.read_count += 1
        if self._reads:
            return self._reads.pop(0) if len(self._reads) > 1 else self._reads[0]
        return (True, "frame")

    def get_resolution(self):
        return self._resolution

    def release(self) -> None:
        self.released = True


class SlowFakeSource(FakeSource):
    """A read() that takes real wall-clock time to return -- simulates the
    belt-and-braces stall check catching a timeout OpenCV's own property did
    not honour."""

    def __init__(self, delay_seconds: float, **kwargs):
        super().__init__([(True, "frame")], **kwargs)
        self._delay = delay_seconds

    def read(self):
        time.sleep(self._delay)
        return super().read()


def make_worker(camera=None, source_factory=None, **overrides) -> tuple[CameraCaptureWorker, dict]:
    events: list = []
    frames: list[bytes] = []
    calls = {"factory_count": 0, "sources": []}

    def factory(url, transport, open_timeout, stall_timeout):
        calls["factory_count"] += 1
        source = source_factory(url, transport, open_timeout, stall_timeout) if source_factory else FakeSource([(True, "frame")])
        calls["sources"].append(source)
        return source

    defaults = {
        "camera": camera or make_camera(),
        "cafe_id": "cafe-1",
        "worker_id": "worker-1",
        "publish": lambda event: events.append(event) or True,
        "publish_frame": lambda jpeg: frames.append(jpeg),
        "source_factory": factory,
        "encode_jpeg": lambda frame, quality: b"fake-jpeg",
        "open_timeout_seconds": 1.0,
        "stall_timeout_seconds": 0.3,
        "preview_publish_interval_seconds": 0.01,
        "preview_jpeg_quality": 70,
        "stats_publish_interval_seconds": 0.05,
    }
    defaults.update(overrides)
    worker = CameraCaptureWorker(**defaults)
    return worker, {"events": events, "frames": frames, "calls": calls}


def wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class FakeDetector:
    """Stands in for worker.detector.PersonDetector: records every frame it
    was asked to look at, without touching torch/ultralytics at all."""

    def __init__(self, person_count: int = 2, inference_ms: float = 12.5, *, raises: bool = False):
        from worker.detector import BoundingBox, DetectionResult

        self._result = DetectionResult(
            boxes=tuple(BoundingBox(0, 0, 10, 10, 0.9) for _ in range(person_count)),
            inference_ms=inference_ms,
        )
        self._raises = raises
        self.frames_seen: list[object] = []

    def detect(self, frame):
        self.frames_seen.append(frame)
        if self._raises:
            raise RuntimeError("detector exploded")
        return self._result


# --------------------------------------------------------------------------- #
# happy path
# --------------------------------------------------------------------------- #
def test_successful_frames_update_the_latest_frame(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    worker, observed = make_worker(source_factory=lambda *a: FakeSource([(True, "frame-1")]))
    worker.start()
    try:
        assert wait_until(lambda: worker.latest_frame.get() == "frame-1")
    finally:
        worker.stop()


def test_camera_connected_is_emitted_exactly_once_on_success(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    worker, observed = make_worker(source_factory=lambda *a: FakeSource([(True, "frame")]))
    worker.start()
    try:
        assert wait_until(lambda: len(observed["events"]) >= 1)
        time.sleep(0.1)  # give a few more read cycles a chance to run
        connected = [e for e in observed["events"] if str(e.type) == "camera_connected"]
        assert len(connected) == 1
    finally:
        worker.stop()


def test_preview_frames_are_published(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    worker, observed = make_worker(source_factory=lambda *a: FakeSource([(True, "frame")]))
    worker.start()
    try:
        assert wait_until(lambda: len(observed["frames"]) >= 1)
        assert observed["frames"][0] == b"fake-jpeg"
    finally:
        worker.stop()


def test_stats_event_reports_resolution(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")], resolution=(1920, 1080))
    )
    worker.start()
    try:
        def has_stats():
            return any(str(e.type) == "camera_stats" for e in observed["events"])

        assert wait_until(has_stats, timeout=2.0)
        stats = next(e for e in observed["events"] if str(e.type) == "camera_stats")
        assert stats.payload["width"] == 1920
        assert stats.payload["height"] == 1080
        assert stats.payload["fps"] > 0
    finally:
        worker.stop()


# --------------------------------------------------------------------------- #
# failure modes
# --------------------------------------------------------------------------- #
def test_a_camera_that_refuses_to_open_reports_connect_failed(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    worker, observed = make_worker(source_factory=lambda *a: FakeSource([], opens=False))
    worker.start()
    try:
        assert wait_until(lambda: len(observed["events"]) >= 1)
        event = observed["events"][0]
        assert str(event.type) == "camera_disconnected"
        assert event.payload["reason"] == "connect_failed"
    finally:
        worker.stop()


def test_a_read_failure_after_connecting_reports_read_error(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    # First read succeeds (announces connected), second read fails.
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame"), (False, None)])
    )
    worker.start()
    try:
        def has_disconnect():
            return any(str(e.type) == "camera_disconnected" for e in observed["events"])

        assert wait_until(has_disconnect)
        disconnect = next(e for e in observed["events"] if str(e.type) == "camera_disconnected")
        assert disconnect.payload["reason"] == "read_error"
    finally:
        worker.stop()


def test_the_source_is_always_released_even_on_failure(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    worker, observed = make_worker(source_factory=lambda *a: FakeSource([(False, None)]))
    worker.start()
    try:
        assert wait_until(lambda: len(observed["calls"]["sources"]) >= 1)
        time.sleep(0.05)
        assert observed["calls"]["sources"][0].released is True
    finally:
        worker.stop()


def test_a_stall_that_the_source_timeout_did_not_catch_is_caught_by_the_belt_and_braces_check(monkeypatch):
    """Simulates a camera/FFmpeg build where CAP_PROP_READ_TIMEOUT_MSEC is not
    honoured: read() itself blocks past the stall timeout before returning
    successfully. This must still be treated as a failure -- a viewer staring
    at a frozen frame for that long is not 'connected'."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    worker, observed = make_worker(
        source_factory=lambda *a: SlowFakeSource(delay_seconds=0.5),
        stall_timeout_seconds=0.1,
    )
    worker.start()
    try:
        def has_disconnect():
            return any(str(e.type) == "camera_disconnected" for e in observed["events"])

        assert wait_until(has_disconnect, timeout=3.0)
    finally:
        worker.stop()


def test_the_worker_reconnects_after_a_failure(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 0.05)
    monkeypatch.setattr("worker.capture.MAX_BACKOFF_SECONDS", 0.1)
    worker, observed = make_worker(source_factory=lambda *a: FakeSource([], opens=False))
    worker.start()
    try:
        assert wait_until(lambda: observed["calls"]["factory_count"] >= 3, timeout=3.0)
    finally:
        worker.stop()


def test_it_does_not_busy_loop_between_reconnect_attempts(monkeypatch):
    """A dead camera must be retried, not hammered."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 0.05)
    monkeypatch.setattr("worker.capture.MAX_BACKOFF_SECONDS", 0.2)
    worker, observed = make_worker(source_factory=lambda *a: FakeSource([], opens=False))
    worker.start()
    try:
        time.sleep(1.0)
    finally:
        worker.stop()
    # With backoff climbing from 0.05s to a 0.2s cap, one second of wall time
    # allows on the order of ten attempts, not hundreds.
    assert 2 <= observed["calls"]["factory_count"] <= 20


# --------------------------------------------------------------------------- #
# shutdown
# --------------------------------------------------------------------------- #
def test_stop_interrupts_a_long_backoff_wait_immediately(monkeypatch):
    """stop() must not block the manager's shutdown behind a 30-second wait."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 5.0)
    worker, observed = make_worker(source_factory=lambda *a: FakeSource([], opens=False))
    worker.start()

    assert wait_until(lambda: observed["calls"]["factory_count"] >= 1)

    started = time.monotonic()
    worker.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"stop() took {elapsed:.2f}s, should interrupt the backoff wait"


def test_stop_releases_the_active_source(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    worker, observed = make_worker(source_factory=lambda *a: FakeSource([(True, "frame")]))
    worker.start()
    assert wait_until(lambda: len(observed["calls"]["sources"]) >= 1)
    source = observed["calls"]["sources"][0]

    worker.stop()

    assert source.released is True


def test_worker_thread_actually_stops(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    worker, observed = make_worker(source_factory=lambda *a: FakeSource([(True, "frame")]))
    worker.start()
    assert wait_until(lambda: worker.is_alive)
    worker.stop()
    assert worker.is_alive is False


# --------------------------------------------------------------------------- #
# detection (Phase 3)
# --------------------------------------------------------------------------- #
def test_with_no_detector_capture_behaves_exactly_as_before(monkeypatch):
    """Regression guard: detector=None (the default) is capture-only mode,
    unchanged from Phase 2."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    worker, observed = make_worker(source_factory=lambda *a: FakeSource([(True, "frame")]))
    worker.start()
    try:
        assert wait_until(lambda: worker.latest_frame.get() == "frame")
        time.sleep(0.1)
    finally:
        worker.stop()

    def has_stats():
        return any(str(e.type) == "camera_stats" for e in observed["events"])

    assert wait_until(has_stats)
    stats = next(e for e in observed["events"] if str(e.type) == "camera_stats")
    assert "person_count" not in stats.payload
    assert "inference_ms" not in stats.payload


def test_detector_is_called_on_each_frame_at_the_configured_interval(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=3)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        publish_detections=lambda result: observed["detections"].append(result),
    )
    observed["detections"] = []
    worker.start()
    try:
        assert wait_until(lambda: len(detector.frames_seen) >= 1)
        assert wait_until(lambda: len(observed["detections"]) >= 1)
        assert observed["detections"][0].person_count == 3
    finally:
        worker.stop()


def test_detection_ticks_are_throttled_independently_of_frame_arrival(monkeypatch):
    """A camera delivering frames much faster than the detection interval
    must not run inference on every single one -- that is exactly the frame
    dropping spec §22 requires."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector()
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")], read_delay_seconds=0.001),
        detector=detector,
        detection_interval_seconds=0.2,
    )
    worker.start()
    try:
        time.sleep(0.5)
    finally:
        worker.stop()
    # ~0.5s of running time at a 0.2s detection interval is 2-3 ticks, while
    # frames arrived roughly every 1ms -- hundreds of them. A bug that ran
    # detection on every frame would show hundreds of calls here instead.
    assert 1 <= len(detector.frames_seen) <= 5


def test_camera_stats_includes_the_most_recent_detection(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=4, inference_ms=33.7)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(detector.frames_seen) >= 1)

        def has_stats_with_detection():
            return any(
                str(e.type) == "camera_stats" and "person_count" in e.payload
                for e in observed["events"]
            )

        assert wait_until(has_stats_with_detection, timeout=2.0)
        stats = next(
            e for e in observed["events"] if str(e.type) == "camera_stats" and "person_count" in e.payload
        )
        assert stats.payload["person_count"] == 4
        assert stats.payload["inference_ms"] == pytest.approx(33.7)
    finally:
        worker.stop()


def test_a_detection_failure_does_not_disconnect_the_camera(monkeypatch):
    """A corrupt frame or a transient inference error is not a camera
    problem -- capture must keep going."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(raises=True)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(detector.frames_seen) >= 1)
        time.sleep(0.1)
        assert not any(str(e.type) == "camera_disconnected" for e in observed["events"])
        assert any(str(e.type) == "camera_connected" for e in observed["events"])
    finally:
        worker.stop()


# --------------------------------------------------------------------------- #
# tracking (Phase 4)
# --------------------------------------------------------------------------- #
class FakeTracker:
    """Stands in for worker.tracker.PersonTracker: records every
    (detection_result, frame) pair it was asked to update with, without
    touching the real ByteTrack/BoT-SORT implementation at all."""

    def __init__(self, track_count: int = 2, *, raises: bool = False):
        from worker.tracker import TrackedBox, TrackingResult

        self._result = TrackingResult(
            boxes=tuple(
                TrackedBox(track_id=i, x1=0, y1=0, x2=10, y2=10, confidence=0.9)
                for i in range(track_count)
            )
        )
        self._raises = raises
        self.updates_seen: list[object] = []

    def update(self, detection_result, frame=None):
        self.updates_seen.append(detection_result)
        if self._raises:
            raise RuntimeError("tracker exploded")
        return self._result


def test_with_no_tracker_capture_behaves_exactly_as_before(monkeypatch):
    """Regression guard: tracker=None (the default) leaves detection-only
    behaviour, unchanged from Phase 3."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=2)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(detector.frames_seen) >= 1)
        time.sleep(0.1)
    finally:
        worker.stop()

    def has_stats():
        return any(str(e.type) == "camera_stats" for e in observed["events"])

    assert wait_until(has_stats)
    stats = next(e for e in observed["events"] if str(e.type) == "camera_stats")
    assert "track_count" not in stats.payload


def test_tracker_is_updated_on_every_detection_tick(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=2)
    tracker = FakeTracker(track_count=2)
    observed = {"tracking": []}
    worker, _observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
        publish_tracking=lambda result: observed["tracking"].append(result),
    )
    worker.start()
    try:
        assert wait_until(lambda: len(tracker.updates_seen) >= 1)
        assert wait_until(lambda: len(observed["tracking"]) >= 1)
        assert observed["tracking"][0].track_count == 2
    finally:
        worker.stop()


def test_tracker_receives_the_detection_result_object(monkeypatch):
    """The tracker must see this tick's actual detections, not something
    reconstructed -- occlusion recovery depends on the real confidences."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=5)
    tracker = FakeTracker()
    worker, _observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(tracker.updates_seen) >= 1)
    finally:
        worker.stop()

    assert tracker.updates_seen[0].person_count == 5


def test_camera_stats_includes_track_count(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=3)
    tracker = FakeTracker(track_count=2)  # deliberately different from person_count
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(tracker.updates_seen) >= 1)

        def has_stats_with_tracking():
            return any(
                str(e.type) == "camera_stats" and "track_count" in e.payload
                for e in observed["events"]
            )

        assert wait_until(has_stats_with_tracking, timeout=2.0)
        stats = next(
            e for e in observed["events"] if str(e.type) == "camera_stats" and "track_count" in e.payload
        )
        assert stats.payload["track_count"] == 2
        assert stats.payload["person_count"] == 3  # the two figures may legitimately differ
    finally:
        worker.stop()


def test_camera_stats_includes_the_active_track_id_roster(monkeypatch):
    """The fallback half of entry/exit detection (Phase 5): the backend uses
    this roster to recognise a track is still present even without a fresh
    crossing event, so a session can eventually be closed at its last
    confirmed sighting if the person is lost without a clean exit."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=2)
    tracker = FakeTracker(track_count=2)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(tracker.updates_seen) >= 1)

        def has_stats_with_tracking():
            return any(
                str(e.type) == "camera_stats" and "active_track_ids" in e.payload
                for e in observed["events"]
            )

        assert wait_until(has_stats_with_tracking, timeout=2.0)
        stats = next(
            e for e in observed["events"]
            if str(e.type) == "camera_stats" and "active_track_ids" in e.payload
        )
        assert stats.payload["active_track_ids"] == [0, 1]
    finally:
        worker.stop()


def test_camera_stats_omits_the_roster_when_there_is_no_tracker(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=2)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(detector.frames_seen) >= 1)
        time.sleep(0.1)
    finally:
        worker.stop()

    def has_stats():
        return any(str(e.type) == "camera_stats" for e in observed["events"])

    assert wait_until(has_stats)
    stats = next(e for e in observed["events"] if str(e.type) == "camera_stats")
    assert "active_track_ids" not in stats.payload


def test_a_tracking_failure_does_not_disconnect_the_camera(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(raises=True)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(tracker.updates_seen) >= 1)
        time.sleep(0.1)
        assert not any(str(e.type) == "camera_disconnected" for e in observed["events"])
    finally:
        worker.stop()


def test_the_tracker_is_never_ticked_when_there_is_no_detector():
    """Tracking has nothing to associate without a detector producing
    detections for it -- there is no meaningful "tracker but no detector"
    configuration."""
    tracker = FakeTracker()
    worker, _observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        tracker=tracker,
    )
    worker.start()
    try:
        time.sleep(0.1)
    finally:
        worker.stop()
    assert tracker.updates_seen == []


# --------------------------------------------------------------------------- #
# zone crossings (Phase 5)
# --------------------------------------------------------------------------- #
class FakeZoneDetector:
    """Stands in for worker.zones.ZoneCrossingDetector: records every
    TrackingResult it was asked to update with, and returns a scripted list
    of crossings."""

    def __init__(self, crossings=None, *, raises: bool = False):
        self._crossings = crossings or []
        self._raises = raises
        self.updates_seen: list[object] = []

    def update(self, tracking_result):
        self.updates_seen.append(tracking_result)
        if self._raises:
            raise RuntimeError("zone detector exploded")
        return self._crossings


def make_crossing(track_id=1, zone_id="z1", zone_name="Front door", direction="entry", x=50.0, y=110.0):
    from worker.zones import CrossingEvent

    return CrossingEvent(track_id=track_id, zone_id=zone_id, zone_name=zone_name, direction=direction, x=x, y=y)


def test_with_no_zone_detector_capture_behaves_exactly_as_before(monkeypatch):
    """Regression guard: zone_detector=None (the default) leaves tracking-only
    behaviour, unchanged from Phase 4."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(track_count=1)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(tracker.updates_seen) >= 1)
        time.sleep(0.1)
    finally:
        worker.stop()
    assert not any(str(e.type) in ("person_entered", "person_exited") for e in observed["events"])


def test_zone_detector_is_updated_on_every_tracking_tick(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(track_count=1)
    zone_detector = FakeZoneDetector()
    worker, _observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
        zone_detector=zone_detector,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(zone_detector.updates_seen) >= 1)
    finally:
        worker.stop()

    assert zone_detector.updates_seen[0].track_count == 1


def test_an_entry_crossing_publishes_a_person_entered_event(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(track_count=1)
    zone_detector = FakeZoneDetector([make_crossing(direction="entry")])
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
        zone_detector=zone_detector,
    )
    worker.start()
    try:
        def has_entry():
            return any(str(e.type) == "person_entered" for e in observed["events"])

        assert wait_until(has_entry, timeout=2.0)
    finally:
        worker.stop()

    event = next(e for e in observed["events"] if str(e.type) == "person_entered")
    assert event.payload == {
        "track_id": 1, "zone_id": "z1", "zone_name": "Front door", "x": 50.0, "y": 110.0,
    }


def test_an_exit_crossing_publishes_a_person_exited_event(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(track_count=1)
    zone_detector = FakeZoneDetector([make_crossing(direction="exit")])
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
        zone_detector=zone_detector,
    )
    worker.start()
    try:
        def has_exit():
            return any(str(e.type) == "person_exited" for e in observed["events"])

        assert wait_until(has_exit, timeout=2.0)
    finally:
        worker.stop()


def test_multiple_crossings_in_one_tick_each_publish_their_own_event(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=2)
    tracker = FakeTracker(track_count=2)
    zone_detector = FakeZoneDetector(
        [make_crossing(track_id=1, direction="entry"), make_crossing(track_id=2, direction="exit")]
    )
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
        zone_detector=zone_detector,
    )
    worker.start()
    try:
        def has_both():
            types = {str(e.type) for e in observed["events"]}
            return "person_entered" in types and "person_exited" in types

        assert wait_until(has_both, timeout=2.0)
    finally:
        worker.stop()


def test_a_zone_crossing_failure_does_not_disconnect_the_camera(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(track_count=1)
    zone_detector = FakeZoneDetector(raises=True)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
        zone_detector=zone_detector,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(zone_detector.updates_seen) >= 1)
        time.sleep(0.1)
        assert not any(str(e.type) == "camera_disconnected" for e in observed["events"])
    finally:
        worker.stop()


def test_the_zone_detector_is_never_ticked_when_there_is_no_tracker():
    """Zone crossing needs track ids to attribute a crossing to, and has
    nothing to check without a tracker producing them."""
    zone_detector = FakeZoneDetector()
    worker, _observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        zone_detector=zone_detector,
    )
    worker.start()
    try:
        time.sleep(0.1)
    finally:
        worker.stop()
    assert zone_detector.updates_seen == []


# --------------------------------------------------------------------------- #
# table occupancy (Phase 9)
# --------------------------------------------------------------------------- #
class FakeTableDetector:
    """Stands in for worker.tables.TableOccupancyDetector: records every
    TrackingResult it was asked to update with, and returns a scripted list
    of occupancy changes."""

    def __init__(self, changes=None, *, raises: bool = False, occupied_ids=None):
        self._changes = changes or []
        self._raises = raises
        self._occupied_ids = occupied_ids or []
        self.updates_seen: list[object] = []

    def update(self, tracking_result):
        self.updates_seen.append(tracking_result)
        if self._raises:
            raise RuntimeError("table detector exploded")
        return self._changes

    def occupied_table_ids(self):
        return self._occupied_ids


def make_table_change(table_id="t1", table_name="Table 1", event="occupied"):
    from worker.tables import TableOccupancyEvent

    return TableOccupancyEvent(table_id=table_id, table_name=table_name, event=event)


def test_with_no_table_detector_capture_behaves_exactly_as_before(monkeypatch):
    """Regression guard: table_detector=None (the default) leaves
    tracking-only behaviour unchanged."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(track_count=1)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(tracker.updates_seen) >= 1)
        time.sleep(0.1)
    finally:
        worker.stop()
    assert not any(str(e.type) in ("table_occupied", "table_released") for e in observed["events"])


def test_table_detector_is_updated_on_every_tracking_tick(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(track_count=1)
    table_detector = FakeTableDetector()
    worker, _observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
        table_detector=table_detector,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(table_detector.updates_seen) >= 1)
    finally:
        worker.stop()

    assert table_detector.updates_seen[0].track_count == 1


def test_an_occupied_change_publishes_a_table_occupied_event(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(track_count=1)
    table_detector = FakeTableDetector([make_table_change(event="occupied")])
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
        table_detector=table_detector,
    )
    worker.start()
    try:
        def has_occupied():
            return any(str(e.type) == "table_occupied" for e in observed["events"])

        assert wait_until(has_occupied, timeout=2.0)
    finally:
        worker.stop()

    event = next(e for e in observed["events"] if str(e.type) == "table_occupied")
    assert event.payload == {"table_id": "t1", "table_name": "Table 1"}


def test_a_released_change_publishes_a_table_released_event(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(track_count=1)
    table_detector = FakeTableDetector([make_table_change(event="released")])
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
        table_detector=table_detector,
    )
    worker.start()
    try:
        def has_released():
            return any(str(e.type) == "table_released" for e in observed["events"])

        assert wait_until(has_released, timeout=2.0)
    finally:
        worker.stop()


def test_a_table_occupancy_failure_does_not_disconnect_the_camera(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(track_count=1)
    table_detector = FakeTableDetector(raises=True)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
        table_detector=table_detector,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(table_detector.updates_seen) >= 1)
        time.sleep(0.1)
        assert not any(str(e.type) == "camera_disconnected" for e in observed["events"])
    finally:
        worker.stop()


def test_the_table_detector_is_never_ticked_when_there_is_no_tracker():
    table_detector = FakeTableDetector()
    worker, _observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        table_detector=table_detector,
    )
    worker.start()
    try:
        time.sleep(0.1)
    finally:
        worker.stop()
    assert table_detector.updates_seen == []


def test_camera_stats_includes_the_occupied_table_id_roster(monkeypatch):
    """The fallback half of table occupancy tracking (Phase 9): the backend
    uses this roster to recognise a table is still occupied even without a
    fresh table_occupied event, so a stuck-open TableSession can eventually
    be closed if the worker goes quiet without a clean release."""
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    tracker = FakeTracker(track_count=1)
    table_detector = FakeTableDetector(occupied_ids=["t1", "t2"])
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
        tracker=tracker,
        table_detector=table_detector,
    )
    worker.start()
    try:
        def has_stats_with_tables():
            return any(
                str(e.type) == "camera_stats" and "occupied_table_ids" in e.payload
                for e in observed["events"]
            )

        assert wait_until(has_stats_with_tables, timeout=2.0)
    finally:
        worker.stop()

    stats = next(
        e for e in observed["events"]
        if str(e.type) == "camera_stats" and "occupied_table_ids" in e.payload
    )
    assert stats.payload["occupied_table_ids"] == ["t1", "t2"]


def test_camera_stats_omits_the_table_roster_when_there_is_no_table_detector(monkeypatch):
    monkeypatch.setattr("worker.capture.INITIAL_BACKOFF_SECONDS", 10.0)
    detector = FakeDetector(person_count=1)
    worker, observed = make_worker(
        source_factory=lambda *a: FakeSource([(True, "frame")]),
        detector=detector,
        detection_interval_seconds=0.01,
    )
    worker.start()
    try:
        assert wait_until(lambda: len(detector.frames_seen) >= 1)
        time.sleep(0.1)
    finally:
        worker.stop()

    def has_stats():
        return any(str(e.type) == "camera_stats" for e in observed["events"])

    assert wait_until(has_stats)
    stats = next(e for e in observed["events"] if str(e.type) == "camera_stats")
    assert "occupied_table_ids" not in stats.payload
