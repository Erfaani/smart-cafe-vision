"""Worker main loop.

Responsibility, in full as of Phase 3:

  * announce that the worker started, and with which real capabilities --
    including "person_detection" only if a model actually finished loading
  * keep a heartbeat alive so the dashboard can show "AI worker online"
  * run the CameraManager, which keeps a capture connection open per
    configured camera, reconnects on failure, and runs detection on the
    frames it captures if a model is available
  * shut down cleanly, announcing that it stopped

Tracking, entry/exit detection and stay time are still not here, and none of
it is simulated. Reporting a customer count with nothing behind it would be
worse than an empty dashboard: a café owner could make staffing decisions on
invented data. That starts in Phase 4.
"""
from __future__ import annotations

import logging
import signal
import time
from types import FrameType

from scv_contracts import Event, EventType
from worker import __version__
from worker.config import WorkerConfig
from worker.detector import build_detector, resolve_model_path
from worker.manager import CameraManager
from worker.publisher import EventPublisher

logger = logging.getLogger("scv.worker")


class WorkerRunner:
    def __init__(
        self,
        config: WorkerConfig,
        publisher: EventPublisher | None = None,
        camera_manager: CameraManager | None = None,
    ) -> None:
        self.config = config
        self.publisher = publisher or EventPublisher(
            config.redis_url, config.stream_key, config.stream_maxlen
        )
        # None until run(): building the default CameraManager loads a YOLO
        # model, which is slow, one-time I/O that has no business happening
        # just from constructing a WorkerRunner. Every test that cares about
        # timing injects its own camera_manager and never touches this path;
        # only main() -> run() takes it in production.
        self.camera_manager: CameraManager | None = camera_manager
        self._running = False

    # -- lifecycle ----------------------------------------------------------
    def _install_signal_handlers(self) -> None:
        def stop(signum: int, _frame: FrameType | None) -> None:
            logger.info("shutdown_requested signal=%s", signum)
            self._running = False

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, stop)
            except ValueError:  # pragma: no cover - not on the main thread
                pass

    def _event(self, event_type: EventType, **payload) -> Event:
        return Event(
            type=event_type,
            cafe_id=self.config.cafe_id,
            worker_id=self.config.worker_id,
            payload=payload,
        )

    def run(self) -> int:
        if not self.config.cafe_id:
            logger.error(
                "CAFE_ID is not set. Find it with "
                "`python manage.py shell -c \"from apps.tenants.models import Cafe; "
                "print(Cafe.objects.first().id)\"`."
            )
            return 2

        self._install_signal_handlers()
        self._running = True

        logger.info(
            "worker_starting id=%s cafe=%s device=%s target_fps=%.1f",
            self.config.worker_id,
            self.config.cafe_id,
            self.config.device,
            self.config.target_fps,
        )

        if self.camera_manager is None:
            detector = None
            if self.config.detection_enabled:
                model_path = resolve_model_path(self.config.model, self.config.models_dir)
                detector = build_detector(
                    model_path, self.config.device, self.config.confidence_threshold
                )
            self.camera_manager = CameraManager(self.config, self.publisher, detector=detector)

        # Capabilities are computed from what actually loaded, not from
        # configuration: AI_DETECTION_ENABLED=true with a model that failed to
        # load (no internet on first run, an unsupported CPU, out of memory)
        # must report camera_capture only, exactly like AI_DETECTION_ENABLED
        # being false in the first place.
        capabilities = ["camera_capture"]
        if self.camera_manager.has_detector:
            capabilities.append("person_detection")
            # Tracking has no separate on/off switch: it runs automatically
            # whenever detection does, adding negligible cost on top of a
            # detection tick that already ran (see worker/tracker.py).
            capabilities.append("multi_object_tracking")

        self.publisher.publish(
            self._event(
                EventType.WORKER_STARTED,
                version=__version__,
                device=self.config.device,
                target_fps=self.config.target_fps,
                capabilities=capabilities,
            )
        )

        self.camera_manager.start()
        try:
            self._heartbeat_loop()
        finally:
            self.camera_manager.stop()
            self.publisher.heartbeat(self.config.worker_id, ttl_seconds=1)
            self.publisher.publish(self._event(EventType.WORKER_STOPPED))
            self.publisher.close()
            logger.info("worker_stopped id=%s", self.config.worker_id)

        return 0

    def _heartbeat_loop(self) -> None:
        interval = max(1.0, self.config.heartbeat_interval_seconds)
        # TTL comfortably longer than the interval so one slow tick does not
        # make the dashboard flap between online and offline.
        ttl = int(interval * 3)
        next_beat = 0.0

        while self._running:
            now = time.monotonic()
            if now >= next_beat:
                self.publisher.heartbeat(self.config.worker_id, ttl_seconds=ttl)
                if self.publisher.buffered_count:
                    logger.warning(
                        "events_buffered count=%d (Redis unreachable)",
                        self.publisher.buffered_count,
                    )
                next_beat = now + interval

            # Short sleep so SIGTERM is noticed promptly: a container that takes
            # 10 seconds to die gets SIGKILLed mid-write.
            time.sleep(0.25)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    return WorkerRunner(WorkerConfig.from_env()).run()
