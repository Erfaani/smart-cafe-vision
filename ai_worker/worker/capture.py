"""Per-camera capture loop: connect, read frames, reconnect on failure.

The one property this module exists to guarantee -- and the thing the roadmap
calls out as the actual hard part of this phase: a camera that misbehaves
(refuses the connection, accepts it and then answers nothing, drops mid-
stream) must not leak a file descriptor, must not block the process, and must
eventually be retried. "Eventually" backs off exponentially so a genuinely
dead camera does not spin the CPU or spam the event log all night.

Every dependency that touches hardware or Redis is injected (`source_factory`,
`encode_jpeg`, `publish_frame`, `publish`), so the state machine here is
testable with plain fakes -- no OpenCV, no camera, no Redis.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from scv_contracts import Event, EventType, utcnow
from scv_contracts.redact import redact_rtsp_credentials
from worker.detector import DetectionResult, PersonDetector
from worker.tables import TableOccupancyDetector, TableOccupancyEvent, TableZoneConfig
from worker.tracker import PersonTracker, TrackingResult
from worker.zones import CrossingEvent, ZoneConfig, ZoneCrossingDetector

logger = logging.getLogger("scv.worker.capture")

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0
# A connection this stable resets the backoff -- otherwise one bad reconnect
# early in the night would leave every later reconnect waiting the full 30s,
# even once the camera has been healthy for hours.
BACKOFF_RESET_AFTER_SECONDS = 60.0


class VideoSource(Protocol):
    def is_opened(self) -> bool: ...
    def read(self) -> tuple[bool, object]: ...
    def get_resolution(self) -> tuple[int, int]: ...
    def release(self) -> None: ...


SourceFactory = Callable[[str, str, float, float], VideoSource]
JpegEncoder = Callable[[object, int], "bytes | None"]


@dataclass(slots=True)
class CameraConfig:
    """What a capture worker needs, decoupled from the backend's JSON shape."""

    id: str
    name: str
    url: str
    transport: str
    zones: tuple[ZoneConfig, ...] = ()
    tables: tuple[TableZoneConfig, ...] = ()

    @property
    def config_signature(self) -> tuple[str, str, tuple[ZoneConfig, ...], tuple[TableZoneConfig, ...]]:
        """What the manager diffs on to detect an edited camera.

        Zones and tables are included deliberately: an edited entrance line
        or table rectangle needs a fresh detector (position/occupancy state
        is meaningless against a moved line or rectangle), and the manager
        already restarts the whole capture worker on any signature change --
        simpler and safer than hot-swapping just one detector inside a
        running one.
        """
        return (self.url, self.transport, self.zones, self.tables)


class LatestFrame:
    """Thread-safe holder for the most recently decoded frame."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: object = None

    def set(self, frame: object) -> None:
        with self._lock:
            self._frame = frame

    def get(self) -> object:
        with self._lock:
            return self._frame


class CameraCaptureWorker:
    """Owns one camera's connection for its whole lifetime, on its own thread."""

    def __init__(
        self,
        camera: CameraConfig,
        *,
        cafe_id: str,
        worker_id: str,
        publish: Callable[[Event], bool],
        publish_frame: Callable[[bytes], None],
        source_factory: SourceFactory,
        encode_jpeg: JpegEncoder,
        open_timeout_seconds: float,
        stall_timeout_seconds: float,
        preview_publish_interval_seconds: float,
        preview_jpeg_quality: int,
        stats_publish_interval_seconds: float,
        detector: PersonDetector | None = None,
        detection_interval_seconds: float = 1.0,
        publish_detections: Callable[[DetectionResult], None] | None = None,
        tracker: PersonTracker | None = None,
        publish_tracking: Callable[[TrackingResult], None] | None = None,
        zone_detector: ZoneCrossingDetector | None = None,
        table_detector: TableOccupancyDetector | None = None,
    ) -> None:
        self.camera = camera
        self._cafe_id = cafe_id
        self._worker_id = worker_id
        self._publish = publish
        self._publish_frame = publish_frame
        self._source_factory = source_factory
        self._encode_jpeg = encode_jpeg
        self._open_timeout = open_timeout_seconds
        self._stall_timeout = stall_timeout_seconds
        self._preview_interval = preview_publish_interval_seconds
        self._preview_quality = preview_jpeg_quality
        self._stats_interval = stats_publish_interval_seconds
        # None is a real, supported mode -- capture-only, no detection stack
        # loaded or AI_DETECTION_ENABLED=false. See worker/detector.py.
        self._detector = detector
        self._detection_interval = detection_interval_seconds
        self._publish_detections = publish_detections
        self._last_detection: DetectionResult | None = None
        # One tracker per camera, never shared -- see worker/tracker.py's
        # module docstring for why sharing one across cameras would conflate
        # their tracks. None whenever `detector` is None: tracking has
        # nothing to associate without detections to feed it.
        self._tracker = tracker
        self._publish_tracking = publish_tracking
        self._last_tracking: TrackingResult | None = None
        # Entry/exit crossings (Phase 5). None whenever there is no tracker:
        # zone crossing needs track ids to attribute a crossing to, and has
        # nothing to check without them.
        self._zone_detector = zone_detector
        # Table occupancy (Phase 9). Also needs tracked boxes -- an
        # untracked detection has no way to debounce occupancy across ticks.
        self._table_detector = table_detector

        self.latest_frame = LatestFrame()
        # Starts CLEAR, set by stop(). This -- not an Event that starts SET --
        # is what makes the backoff wait below actually wait: Event.wait()
        # returns immediately when the event is already set, so an Event
        # meant to mean "still running" (set while active) makes every
        # wait() on it during normal operation a no-op. An earlier version of
        # this file had exactly that bug: the backoff between reconnect
        # attempts never actually elapsed, and a camera that refused every
        # connection was retried tens of thousands of times a second instead
        # of once every few seconds.
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ------------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name=f"camera-{self.camera.id}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._open_timeout + 5)

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- main loop --------------------------------------------------------------
    def _run(self) -> None:
        backoff = INITIAL_BACKOFF_SECONDS

        while not self._stop_event.is_set():
            connected_at: float | None = None
            source: VideoSource | None = None
            try:
                source = self._source_factory(
                    self.camera.url, self.camera.transport, self._open_timeout, self._stall_timeout
                )
                if not source.is_opened():
                    raise ConnectionError("stream did not open")

                connected_at = time.monotonic()
                self._capture_until_failure(source)
            except Exception as exc:  # noqa: BLE001 - any failure here means reconnect, never crash the thread
                reason = "connect_failed" if connected_at is None else "read_error"
                self._emit_disconnected(reason=reason, error=str(exc))
            finally:
                if source is not None:
                    source.release()

            if self._stop_event.is_set():
                break

            if connected_at is not None and time.monotonic() - connected_at > BACKOFF_RESET_AFTER_SECONDS:
                backoff = INITIAL_BACKOFF_SECONDS

            # Blocks up to `backoff` seconds, but returns immediately once
            # stop() sets the event -- so shutdown never waits behind a long
            # reconnect backoff.
            self._stop_event.wait(timeout=backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    def _capture_until_failure(self, source: VideoSource) -> None:
        connected_announced = False
        last_frame_time = time.monotonic()
        last_preview_time = 0.0
        last_stats_time = 0.0
        last_detection_time = 0.0
        frames_since_stats = 0

        while not self._stop_event.is_set():
            ok, frame = source.read()
            now = time.monotonic()

            if not ok or frame is None:
                raise ConnectionError("read() returned no frame")

            if now - last_frame_time > self._stall_timeout:
                # Belt-and-braces: OpenCV's own read timeout (set in
                # rtsp_client.py) should already have turned a stall into
                # ok=False above. This catches the case where a given
                # camera/FFmpeg build does not honour that property.
                raise ConnectionError("stream stalled: no frame within timeout")

            last_frame_time = now
            self.latest_frame.set(frame)
            frames_since_stats += 1

            if not connected_announced:
                self._emit_connected()
                connected_announced = True

            if now - last_preview_time >= self._preview_interval:
                self._publish_preview(frame)
                last_preview_time = now

            if self._detector is not None and now - last_detection_time >= self._detection_interval:
                self._run_detection(frame)
                last_detection_time = now

            if now - last_stats_time >= self._stats_interval:
                elapsed = (now - last_stats_time) if last_stats_time else self._stats_interval
                fps = frames_since_stats / max(elapsed, 0.001)
                width, height = source.get_resolution()
                self._emit_stats(fps=fps, width=width, height=height)
                frames_since_stats = 0
                last_stats_time = now

    # -- event helpers ----------------------------------------------------------
    def _event(self, event_type: EventType, payload: dict) -> Event:
        return Event(
            type=event_type,
            cafe_id=self._cafe_id,
            camera_id=self.camera.id,
            worker_id=self._worker_id,
            occurred_at=utcnow(),
            payload=payload,
        )

    def _emit_connected(self) -> None:
        logger.info("camera_connected camera=%s name=%s", self.camera.id, self.camera.name)
        self._publish(self._event(EventType.CAMERA_CONNECTED, {}))

    def _emit_disconnected(self, *, reason: str, error: str) -> None:
        safe_error = redact_rtsp_credentials(error)[:200]
        logger.warning(
            "camera_disconnected camera=%s reason=%s error=%s", self.camera.id, reason, safe_error
        )
        self._publish(
            self._event(EventType.CAMERA_DISCONNECTED, {"reason": reason, "error": safe_error})
        )

    def _emit_stats(self, *, fps: float, width: int, height: int) -> None:
        payload = {"fps": round(fps, 2), "width": width, "height": height}
        if self._last_detection is not None:
            # Whatever the most recent detection tick found -- not re-run
            # here. camera_stats reports on a slower cadence than detection
            # runs, so this is a snapshot, not a fresh measurement.
            payload["person_count"] = self._last_detection.person_count
            payload["inference_ms"] = round(self._last_detection.inference_ms, 1)
        if self._last_tracking is not None:
            # Deliberately a separate field from person_count, not a
            # duplicate: they can genuinely differ. person_count is this
            # instant's raw detector output; track_count is the tracker's
            # considered view, which keeps a person who was only briefly
            # missed (occlusion, a bad frame) counted through the gap instead
            # of flickering to zero and back.
            payload["track_count"] = self._last_tracking.track_count
            # The fallback half of entry/exit detection (Phase 5): a clean
            # exit-line crossing is the primary way a customer session ends,
            # but a person can also simply leave the camera's coverage
            # entirely -- an uncovered door, or the worker restarting and
            # losing all track state. This roster lets the backend recognise
            # "this track is still here" independently of any crossing event,
            # so a session with no matching id in recent rosters can
            # eventually be closed at its last confirmed sighting rather than
            # staying open forever. See apps/sessions/tasks.py on the backend.
            payload["active_track_ids"] = [b.track_id for b in self._last_tracking.boxes]
        if self._table_detector is not None:
            # The same fallback-roster idea as active_track_ids above, for
            # tables (Phase 9): a table_occupied event only fires once, on
            # the debounced transition, so this heartbeat is what lets the
            # backend notice a still-occupied table whose worker went quiet
            # without ever publishing a matching table_released. See
            # apps/tables/tasks.py on the backend.
            payload["occupied_table_ids"] = self._table_detector.occupied_table_ids()
        self._publish(self._event(EventType.CAMERA_STATS, payload))

    def _publish_preview(self, frame: object) -> None:
        jpeg = self._encode_jpeg(frame, self._preview_quality)
        if jpeg is not None:
            self._publish_frame(jpeg)

    def _run_detection(self, frame: object) -> None:
        try:
            result = self._detector.detect(frame)
        except Exception:
            # A detection failure (a corrupt frame, a transient CUDA hiccup)
            # must not be treated as a camera disconnect -- capture keeps
            # going, this tick's detection is just skipped. Tracking is
            # skipped along with it: both advance together or not at all, so
            # neither's internal frame counter drifts from the other's.
            logger.exception("detection_failed camera=%s", self.camera.id)
            return
        self._last_detection = result
        if self._publish_detections is not None:
            self._publish_detections(result)

        if self._tracker is not None:
            try:
                # Ticked unconditionally, including when person_count == 0:
                # PersonTracker.update() must see every tick to keep its
                # occlusion/lost-track timing correct (see worker/tracker.py).
                tracking_result = self._tracker.update(result, frame)
            except Exception:
                # PersonTracker.update() already catches its own failures
                # internally and never raises; this is defense in depth for
                # whatever else `tracker` might be, same principle as the
                # detector try/except above -- one bad tick must not read as
                # a camera disconnect.
                logger.exception("tracking_failed camera=%s", self.camera.id)
                return
            self._last_tracking = tracking_result
            if self._publish_tracking is not None:
                self._publish_tracking(tracking_result)

            if self._zone_detector is not None:
                self._run_zone_crossings(tracking_result)

            if self._table_detector is not None:
                self._run_table_occupancy(tracking_result)

    def _run_zone_crossings(self, tracking_result: TrackingResult) -> None:
        try:
            # Ticked unconditionally whenever a zone detector is configured,
            # including empty tracking ticks: it must see every tick to keep
            # its own staleness clock correct (see worker/zones.py).
            crossings = self._zone_detector.update(tracking_result)
        except Exception:
            logger.exception("zone_crossing_failed camera=%s", self.camera.id)
            return

        for crossing in crossings:
            self._emit_crossing(crossing)

    def _emit_crossing(self, crossing: CrossingEvent) -> None:
        event_type = EventType.PERSON_ENTERED if crossing.direction == "entry" else EventType.PERSON_EXITED
        logger.info(
            "person_%s camera=%s track=%s zone=%s",
            crossing.direction,
            self.camera.id,
            crossing.track_id,
            crossing.zone_name,
        )
        self._publish(
            self._event(
                event_type,
                {
                    "track_id": crossing.track_id,
                    "zone_id": crossing.zone_id,
                    "zone_name": crossing.zone_name,
                    "x": round(crossing.x, 1),
                    "y": round(crossing.y, 1),
                },
            )
        )

    def _run_table_occupancy(self, tracking_result: TrackingResult) -> None:
        try:
            # Ticked unconditionally whenever a table detector is
            # configured, including empty tracking ticks: it must see every
            # tick to keep its debounce counters correct (see
            # worker/tables.py).
            changes = self._table_detector.update(tracking_result)
        except Exception:
            logger.exception("table_occupancy_failed camera=%s", self.camera.id)
            return

        for change in changes:
            self._emit_table_event(change)

    def _emit_table_event(self, change: TableOccupancyEvent) -> None:
        event_type = EventType.TABLE_OCCUPIED if change.event == "occupied" else EventType.TABLE_RELEASED
        logger.info(
            "table_%s camera=%s table=%s", change.event, self.camera.id, change.table_name
        )
        self._publish(
            self._event(
                event_type,
                {"table_id": change.table_id, "table_name": change.table_name},
            )
        )
