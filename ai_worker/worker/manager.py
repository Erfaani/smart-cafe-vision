"""Reconciles the backend's camera list with running capture workers.

Polling, not push: cameras change rarely (an admin editing one in the
dashboard), so "ask again in a bit" is simpler and more robust here than a
websocket subscription would be, at the cost of an edit taking up to
`camera_poll_interval_seconds` to apply -- a trade worth making for something
this infrequent.

A backend that is briefly unreachable must not tear down cameras that are
already capturing: `fetch_camera_configs` returning None (as opposed to an
empty list) means "could not ask this time", and the manager leaves the
current set exactly as it is until the next successful poll.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable

import redis
import requests

from scv_contracts import utcnow
from scv_contracts.keys import camera_detections_key, camera_frame_key, camera_tracks_key
from worker.capture import CameraCaptureWorker, CameraConfig
from worker.config import WorkerConfig
from worker.detector import DetectionResult, PersonDetector
from worker.publisher import EventPublisher
from worker.rtsp_client import default_jpeg_encoder, default_source_factory
from worker.tables import TableOccupancyDetector, TableZoneConfig
from worker.tracker import PersonTracker, TrackingResult
from worker.zones import ZoneConfig, ZoneCrossingDetector

logger = logging.getLogger("scv.worker.manager")

HTTP_TIMEOUT_SECONDS = 10
# A cached preview frame (or detection summary) outlives one publish interval
# by a wide margin, so a single missed publish does not make the dashboard
# flash "no frame yet". Both expire on their own once a camera genuinely stops
# publishing -- no manual cleanup needed when a camera is disabled, deleted,
# or the worker crashes.
FRAME_TTL_MULTIPLIER = 6
MIN_FRAME_TTL_SECONDS = 5
DETECTIONS_TTL_MULTIPLIER = 6
MIN_DETECTIONS_TTL_SECONDS = 5
TRACKS_TTL_MULTIPLIER = 6
MIN_TRACKS_TTL_SECONDS = 5

CaptureWorkerFactory = Callable[[CameraConfig], CameraCaptureWorker]
ConfigFetcher = Callable[[], "list[CameraConfig] | None"]


def fetch_camera_configs_from_backend(
    backend_url: str, worker_token: str, cafe_id: str
) -> list[CameraConfig] | None:
    """The default fetcher: GET /api/v1/cameras/worker-config/ from the backend.

    Returns None on any failure -- network error, bad status, malformed body --
    so the caller can distinguish "no cameras configured" (empty list) from
    "could not find out" (None). Only the former is safe to reconcile against.
    """
    try:
        response = requests.get(
            f"{backend_url.rstrip('/')}/api/v1/cameras/worker-config/",
            params={"cafe_id": cafe_id},
            headers={"X-Worker-Token": worker_token},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning("camera_config_fetch_failed error=%s", type(exc).__name__)
        return None
    except ValueError:
        logger.warning("camera_config_fetch_invalid_json")
        return None

    try:
        return [
            CameraConfig(
                id=item["id"],
                name=item["name"],
                url=item["url"],
                transport=item["transport"],
                zones=tuple(_parse_zone(zone) for zone in item.get("zones", [])),
                tables=tuple(_parse_table(table) for table in item.get("tables", [])),
            )
            for item in payload
        ]
    except (KeyError, TypeError, IndexError):
        logger.warning("camera_config_fetch_malformed_payload")
        return None


def _parse_zone(item: dict) -> ZoneConfig:
    return ZoneConfig(
        id=item["id"],
        name=item["name"],
        point_a=(item["point_a"][0], item["point_a"][1]),
        point_b=(item["point_b"][0], item["point_b"][1]),
        entry_is_positive_side=bool(item["entry_is_positive_side"]),
    )


def _parse_table(item: dict) -> TableZoneConfig:
    return TableZoneConfig(
        id=item["id"],
        name=item["name"],
        x1=item["x1"],
        y1=item["y1"],
        x2=item["x2"],
        y2=item["y2"],
    )


class CameraManager:
    """Starts, stops and restarts CameraCaptureWorker instances to match the
    backend's camera list."""

    def __init__(
        self,
        config: WorkerConfig,
        publisher: EventPublisher,
        *,
        fetch_camera_configs: ConfigFetcher | None = None,
        capture_worker_factory: CaptureWorkerFactory | None = None,
        redis_client: redis.Redis | None = None,
        detector: PersonDetector | None = None,
    ) -> None:
        self._config = config
        self._publisher = publisher
        # Built once, by the caller (WorkerRunner), and shared by every camera
        # this manager starts -- not one model per camera. None is a real,
        # supported mode: capture-only, see worker/detector.py.
        self._detector = detector
        self._fetch = fetch_camera_configs or (
            lambda: fetch_camera_configs_from_backend(
                config.backend_url, config.worker_token, config.cafe_id
            )
        )
        self._build_worker = capture_worker_factory or self._default_capture_worker_factory
        self._redis = redis_client if redis_client is not None else redis.Redis.from_url(config.redis_url)

        self._workers: dict[str, CameraCaptureWorker] = {}
        self._signatures: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()
        # Starts CLEAR, set by stop() -- see the identical, and identically
        # important, comment on CameraCaptureWorker._stop_event in capture.py.
        # An Event that starts SET would make the poll-interval wait below a
        # no-op, hammering the backend's worker-config endpoint continuously
        # instead of once per `camera_poll_interval_seconds`.
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="camera-manager", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._config.camera_poll_interval_seconds + 5)
        with self._lock:
            for worker in self._workers.values():
                worker.stop()
            self._workers.clear()
            self._signatures.clear()

    @property
    def active_camera_ids(self) -> set[str]:
        with self._lock:
            return set(self._workers)

    @property
    def has_detector(self) -> bool:
        """Whether cameras this manager starts will actually run detection.

        WorkerRunner reads this to decide whether "person_detection" belongs
        in the capabilities it reports -- computed from what actually loaded,
        never assumed from configuration alone.
        """
        return self._detector is not None

    # -- polling loop ------------------------------------------------------------
    def _run(self) -> None:
        # Reconcile once immediately so cameras start capturing without
        # waiting a full poll interval after the worker boots.
        self.poll_once()
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._config.camera_poll_interval_seconds)
            if self._stop_event.is_set():
                break
            self.poll_once()

    def poll_once(self) -> None:
        configs = self._fetch()
        if configs is None:
            return  # backend unreachable: leave the current set exactly as is
        self._reconcile(configs)

    def _reconcile(self, configs: list[CameraConfig]) -> None:
        wanted = {camera.id: camera for camera in configs}

        with self._lock:
            for camera_id in list(self._workers):
                if camera_id not in wanted:
                    logger.info("camera_removed camera=%s", camera_id)
                    self._workers.pop(camera_id).stop()
                    self._signatures.pop(camera_id, None)

            for camera_id, camera in wanted.items():
                existing_signature = self._signatures.get(camera_id)
                if existing_signature is None:
                    logger.info("camera_added camera=%s name=%s", camera_id, camera.name)
                    self._start_worker_locked(camera)
                elif existing_signature != camera.config_signature:
                    logger.info("camera_reconfigured camera=%s name=%s", camera_id, camera.name)
                    self._workers.pop(camera_id).stop()
                    self._start_worker_locked(camera)
                # else: unchanged, leave the running capture connection alone.

    def _start_worker_locked(self, camera: CameraConfig) -> None:
        """Caller must hold `self._lock`."""
        worker = self._build_worker(camera)
        worker.start()
        self._workers[camera.id] = worker
        self._signatures[camera.id] = camera.config_signature

    # -- defaults ---------------------------------------------------------------
    def _default_capture_worker_factory(self, camera: CameraConfig) -> CameraCaptureWorker:
        tracker = self._new_tracker_for_camera(camera.id)
        return CameraCaptureWorker(
            camera,
            cafe_id=self._config.cafe_id,
            worker_id=self._config.worker_id,
            publish=self._publisher.publish,
            publish_frame=self._make_frame_publisher(camera.id),
            source_factory=default_source_factory,
            encode_jpeg=default_jpeg_encoder,
            open_timeout_seconds=self._config.camera_open_timeout_seconds,
            stall_timeout_seconds=self._config.camera_stall_timeout_seconds,
            preview_publish_interval_seconds=self._config.preview_publish_interval_seconds,
            preview_jpeg_quality=self._config.preview_jpeg_quality,
            stats_publish_interval_seconds=self._config.stats_publish_interval_seconds,
            detector=self._detector,
            # target_fps is an inference budget, not a camera frame rate (spec
            # §22) -- one detection every 1/target_fps seconds, independent of
            # how fast frames actually arrive.
            detection_interval_seconds=1.0 / max(self._config.target_fps, 0.1),
            publish_detections=self._make_detection_publisher(camera.id),
            tracker=tracker,
            publish_tracking=self._make_tracking_publisher(camera.id),
            zone_detector=self._new_zone_detector_for_camera(camera, tracker),
            table_detector=self._new_table_detector_for_camera(camera, tracker),
        )

    def _new_tracker_for_camera(self, camera_id: str) -> PersonTracker | None:
        """One tracker per camera -- see worker/tracker.py's module docstring
        for why sharing one across cameras is unsafe. Nothing to track
        without a detector, so this stays None in capture-only mode."""
        if self._detector is None:
            return None
        try:
            return PersonTracker(self._config.tracker_type)
        except Exception:
            # A tracker failing to construct must not take detection or
            # capture down with it, matching the same principle build_detector
            # already applies one layer up.
            logger.exception(
                "tracker_init_failed camera=%s tracker_type=%s -- continuing "
                "without tracking",
                camera_id,
                self._config.tracker_type,
            )
            return None

    def _new_zone_detector_for_camera(
        self, camera: CameraConfig, tracker: PersonTracker | None
    ) -> ZoneCrossingDetector | None:
        """One zone detector per camera, same reasoning as the tracker: its
        crossing state (last known position per track id) is per-camera by
        construction. Nothing to check without a tracker producing track ids,
        and nothing worth checking if the admin has not configured any
        entrance/exit lines for this camera yet."""
        if tracker is None or not camera.zones:
            return None
        try:
            return ZoneCrossingDetector(list(camera.zones))
        except Exception:
            logger.exception(
                "zone_detector_init_failed camera=%s -- continuing without "
                "entry/exit detection",
                camera.id,
            )
            return None

    def _new_table_detector_for_camera(
        self, camera: CameraConfig, tracker: PersonTracker | None
    ) -> TableOccupancyDetector | None:
        """One table detector per camera, same reasoning as the zone
        detector: its debounce state is per-camera by construction. Nothing
        to check without a tracker producing boxes to overlap against a
        table, and nothing worth checking if the admin has not drawn any
        tables for this camera yet."""
        if tracker is None or not camera.tables:
            return None
        try:
            return TableOccupancyDetector(list(camera.tables))
        except Exception:
            logger.exception(
                "table_detector_init_failed camera=%s -- continuing without "
                "table occupancy detection",
                camera.id,
            )
            return None

    def _make_frame_publisher(self, camera_id: str) -> Callable[[bytes], None]:
        key = camera_frame_key(camera_id)
        ttl = max(
            int(self._config.preview_publish_interval_seconds * FRAME_TTL_MULTIPLIER),
            MIN_FRAME_TTL_SECONDS,
        )

        def publish_frame(jpeg: bytes) -> None:
            try:
                self._redis.set(key, jpeg, ex=ttl)
            except redis.RedisError:
                logger.debug("preview_publish_failed camera=%s", camera_id)

        return publish_frame

    def _make_detection_publisher(self, camera_id: str) -> Callable[[DetectionResult], None]:
        key = camera_detections_key(camera_id)
        # A detection tick happens roughly once per 1/target_fps; the TTL only
        # needs to outlive one missed tick, same reasoning as the frame TTL.
        ttl = max(
            int((1.0 / max(self._config.target_fps, 0.1)) * DETECTIONS_TTL_MULTIPLIER),
            MIN_DETECTIONS_TTL_SECONDS,
        )

        def publish_detections(result: DetectionResult) -> None:
            payload = {
                "person_count": result.person_count,
                "inference_ms": round(result.inference_ms, 1),
                "boxes": [
                    {"x1": b.x1, "y1": b.y1, "x2": b.x2, "y2": b.y2, "confidence": b.confidence}
                    for b in result.boxes
                ],
                "updated_at": utcnow().isoformat(),
            }
            try:
                self._redis.set(key, json.dumps(payload), ex=ttl)
            except redis.RedisError:
                logger.debug("detections_publish_failed camera=%s", camera_id)

        return publish_detections

    def _make_tracking_publisher(self, camera_id: str) -> Callable[[TrackingResult], None]:
        key = camera_tracks_key(camera_id)
        ttl = max(
            int((1.0 / max(self._config.target_fps, 0.1)) * TRACKS_TTL_MULTIPLIER),
            MIN_TRACKS_TTL_SECONDS,
        )

        def publish_tracking(result: TrackingResult) -> None:
            payload = {
                "track_count": result.track_count,
                "tracks": [
                    {
                        "track_id": b.track_id,
                        "x1": b.x1,
                        "y1": b.y1,
                        "x2": b.x2,
                        "y2": b.y2,
                        "confidence": b.confidence,
                    }
                    for b in result.boxes
                ],
                "updated_at": utcnow().isoformat(),
            }
            try:
                self._redis.set(key, json.dumps(payload), ex=ttl)
            except redis.RedisError:
                logger.debug("tracking_publish_failed camera=%s", camera_id)

        return publish_tracking
