"""Worker configuration, read from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    worker_id: str
    redis_url: str
    stream_key: str
    stream_maxlen: int
    cafe_id: str

    # Device selection is resolved at runtime in Phase 3; "auto" means use CUDA
    # when it is genuinely available and fall back to CPU otherwise, because a
    # café mini PC may have no GPU at all.
    device: str
    model: str

    # Inference FPS cap. Deliberately independent of camera FPS: a 25 fps camera
    # does not need 25 inferences per second to measure how long someone sits,
    # and pretending otherwise is how a mini PC ends up thermally throttled.
    target_fps: float

    heartbeat_interval_seconds: float

    # -- camera capture (Phase 2) --------------------------------------------
    backend_url: str
    worker_token: str
    # How often to re-fetch the camera list from the backend. Polling, not a
    # push notification: cameras change rarely (an admin editing one in the
    # dashboard), so the simplicity of "ask again in a bit" outweighs the
    # latency of a config change taking up to this long to apply.
    camera_poll_interval_seconds: float
    # If cv2.VideoCapture.open() has not returned within this long, treat it as
    # failed. Maps to FFmpeg's connection timeout.
    camera_open_timeout_seconds: float
    # If no frame has been read within this long even though the stream is
    # "open", treat the connection as stalled and reconnect. This is the
    # camera that answers TCP but never sends a frame -- the failure mode a
    # bare connect-timeout cannot catch, because the connection itself is fine.
    camera_stall_timeout_seconds: float
    # How often to publish a JPEG to Redis for the live preview. Deliberately
    # much slower than the capture rate: the dashboard preview does not need
    # 25 fps, and re-encoding every frame would waste CPU that inference needs.
    preview_publish_interval_seconds: float
    preview_jpeg_quality: int
    # How often to publish camera_stats (observed fps/resolution) for the
    # dashboard's camera health panel.
    stats_publish_interval_seconds: float

    # -- person detection (Phase 3) ------------------------------------------
    # Off entirely is a real, supported mode: a model that fails to load (no
    # internet during setup, an unsupported CPU, out of memory) must not take
    # camera capture and live preview down with it. See worker/detector.py.
    detection_enabled: bool
    # Only detections at or above this confidence count. YOLO's own default
    # (0.25) is tuned for benchmark recall, not for "should this appear as a
    # customer on a dashboard" -- 0.5 trades some recall for fewer spurious
    # boxes on a coat rack or a poster.
    confidence_threshold: float
    # Where a bare model filename (the common case, e.g. "yolo11n.pt") is
    # looked up/downloaded to. Empty means "wherever the process's current
    # working directory is" (fine for local development); in the Docker image
    # this is set to a mounted volume so the one-time download survives a
    # container recreation instead of vanishing with the container's writable
    # layer. See worker/detector.py:resolve_model_path.
    models_dir: str

    # -- multi-object tracking (Phase 4) -------------------------------------
    # "bytetrack" (default) or "botsort". Both are ultralytics' bundled
    # implementations, motion-and-IoU association only -- BoT-SORT's optional
    # appearance/ReID mode is never enabled by this system (spec §26: that
    # mode is a biometric feature). Tracking runs automatically whenever
    # detection does; there is no separate on/off switch for it, since it
    # adds negligible cost on top of a detection tick that already ran.
    tracker_type: str

    @classmethod
    def from_env(cls) -> WorkerConfig:
        return cls(
            worker_id=os.environ.get("AI_WORKER_ID", "worker-1"),
            redis_url=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
            stream_key=os.environ.get("EVENT_STREAM_KEY", "scv:events"),
            stream_maxlen=_int("EVENT_STREAM_MAXLEN", 100000),
            cafe_id=os.environ.get("CAFE_ID", ""),
            device=os.environ.get("AI_DEVICE", "auto"),
            model=os.environ.get("AI_MODEL", "yolo11n.pt"),
            target_fps=_float("AI_TARGET_FPS", 10.0),
            heartbeat_interval_seconds=_float("AI_HEARTBEAT_SECONDS", 10.0),
            backend_url=os.environ.get("BACKEND_INTERNAL_URL", "http://127.0.0.1:8000"),
            worker_token=os.environ.get("AI_WORKER_TOKEN", ""),
            camera_poll_interval_seconds=_float("CAMERA_POLL_INTERVAL_SECONDS", 15.0),
            camera_open_timeout_seconds=_float("CAMERA_OPEN_TIMEOUT_SECONDS", 10.0),
            camera_stall_timeout_seconds=_float("CAMERA_STALL_TIMEOUT_SECONDS", 15.0),
            preview_publish_interval_seconds=_float("CAMERA_PREVIEW_INTERVAL_SECONDS", 0.5),
            preview_jpeg_quality=_int("CAMERA_PREVIEW_JPEG_QUALITY", 70),
            stats_publish_interval_seconds=_float("CAMERA_STATS_INTERVAL_SECONDS", 10.0),
            detection_enabled=_bool("AI_DETECTION_ENABLED", True),
            confidence_threshold=_float("AI_CONFIDENCE_THRESHOLD", 0.5),
            models_dir=os.environ.get("AI_MODELS_DIR", ""),
            tracker_type=os.environ.get("AI_TRACKER", "bytetrack"),
        )
