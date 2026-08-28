"""Person detection: loading a YOLO model and running inference on a frame.

Kept separate from capture.py so the reconnection state machine there never has
to know about torch/ultralytics, and so capture.py stays fully testable (as it
already was in Phase 2) on a machine where the detection stack is unavailable
or has failed to load.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("scv.worker.detector")

# COCO class 0. Every other class YOLO can see in a café (chairs, cups,
# laptops, dogs...) is irrelevant to this product and is filtered out before a
# box ever leaves this module: anonymous *person* counting only (spec §3).
PERSON_CLASS_ID = 0


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float


@dataclass(frozen=True, slots=True)
class DetectionResult:
    boxes: tuple[BoundingBox, ...]
    inference_ms: float

    @property
    def person_count(self) -> int:
        return len(self.boxes)


class YoloModel(Protocol):
    """The one method PersonDetector needs from ultralytics.YOLO -- narrowed
    to a Protocol so tests can supply a fake model with no torch import."""

    def predict(self, source, *, device: str, classes: list[int], conf: float, verbose: bool): ...


def resolve_device(requested: str) -> str:
    """Turn "auto"/"cuda"/"cpu" into an actual torch device string.

    "auto" prefers CUDA when it is genuinely available and falls back to CPU
    otherwise -- a café mini PC may have no GPU at all, and the system must
    still start (spec §23). An explicit "cuda" request is deliberately NOT
    silently downgraded: it raises, so `build_detector` can fail loudly rather
    than quietly running ten times slower on a machine that was bought for its
    GPU with no indication why (see docs/gpu-setup.md).
    """
    if requested == "cpu":
        return "cpu"

    import torch

    cuda_available = torch.cuda.is_available()

    if requested == "cuda":
        if not cuda_available:
            raise RuntimeError(
                "AI_DEVICE=cuda was requested but no CUDA device is available. "
                "Check the NVIDIA driver and the Container Toolkit "
                "(docs/gpu-setup.md), or set AI_DEVICE=auto to fall back to "
                "CPU automatically."
            )
        return "cuda"

    # "auto", or anything unrecognised: treated the same as auto rather than
    # refusing to start over a typo in an environment variable.
    return "cuda" if cuda_available else "cpu"


class PersonDetector:
    """Wraps one loaded YOLO model.

    Thread-safe: every camera's capture thread calls `detect()` on its own
    schedule, and ultralytics model objects are not documented as safe for
    concurrent inference calls from multiple threads, so calls are serialised
    with a lock. At the 1-16 camera scale this product targets that costs
    little -- a shared GPU (or CPU) is the real bottleneck either way, lock or
    not.
    """

    def __init__(self, model: YoloModel, *, device: str, confidence_threshold: float) -> None:
        self._model = model
        self.device = device
        self.confidence_threshold = confidence_threshold
        self._lock = threading.Lock()

    def detect(self, frame: object) -> DetectionResult:
        started = time.monotonic()
        with self._lock:
            results = self._model.predict(
                frame,
                device=self.device,
                classes=[PERSON_CLASS_ID],
                conf=self.confidence_threshold,
                verbose=False,
            )
        inference_ms = (time.monotonic() - started) * 1000

        boxes: list[BoundingBox] = []
        if results:
            result_boxes = results[0].boxes
            if result_boxes is not None:
                xyxy = result_boxes.xyxy.tolist()
                confidences = result_boxes.conf.tolist()
                boxes = [
                    BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=conf)
                    for (x1, y1, x2, y2), conf in zip(xyxy, confidences, strict=True)
                ]

        return DetectionResult(boxes=tuple(boxes), inference_ms=inference_ms)


def resolve_model_path(model: str, models_dir: str) -> str:
    """Where to load/download the model file.

    A bare filename (the common case: AI_MODEL=yolo11n.pt) resolves relative
    to `models_dir` when one is configured -- in the Docker image that is a
    mounted volume (see docker-compose.ai.yml), so the one-time download
    survives a container recreation instead of vanishing with the container's
    writable layer. An absolute path or a URL in `model` is used as-is: an
    operator supplying their own model knows exactly where they put it.
    """
    if not models_dir or Path(model).is_absolute() or "://" in model:
        return model
    return str(Path(models_dir) / model)


def build_detector(
    model_path: str, device_request: str, confidence_threshold: float
) -> PersonDetector | None:
    """Load a YOLO model, or return None if it cannot be loaded.

    Never raises. A model that fails to load -- no internet to fetch weights
    on first run, an unsupported CPU, an explicitly requested GPU that is not
    there, out of memory -- must not take camera capture and the live preview
    down with it. The failure is still loud: an ERROR-level log line, and the
    worker's reported capabilities omit "person_detection", both visible to
    whoever is debugging the install rather than silently degraded.
    """
    try:
        device = resolve_device(device_request)
    except RuntimeError as exc:
        logger.error("detector_device_unavailable error=%s", exc)
        return None

    try:
        from ultralytics import YOLO

        model = YOLO(model_path)

        # A tiny warm-up call, with the exact settings a real detection tick
        # uses (class filter, confidence threshold), so the first real tick --
        # against a live camera frame, whose inference_ms feeds camera_stats --
        # is not also the one paying for lazy CUDA kernel compilation / graph
        # tracing on a code path that hasn't run yet.
        import numpy as np

        model.predict(
            np.zeros((64, 64, 3), dtype=np.uint8),
            device=device,
            classes=[PERSON_CLASS_ID],
            conf=confidence_threshold,
            verbose=False,
        )
    except Exception:
        logger.exception(
            "detector_load_failed model=%s device=%s -- continuing in "
            "capture-only mode",
            model_path,
            device_request,
        )
        return None

    logger.info(
        "detector_loaded model=%s device=%s confidence=%.2f",
        model_path,
        device,
        confidence_threshold,
    )
    return PersonDetector(model, device=device, confidence_threshold=confidence_threshold)
