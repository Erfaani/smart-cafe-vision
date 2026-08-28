"""Person detection, against fake models -- no real inference, no GPU needed.

Confidence filtering and class filtering are ultralytics' own job (passed as
`conf=`/`classes=` into `predict()`); what this module owns is turning YOLO's
result objects into anonymous BoundingBox data, thread-safety around a shared
model, and graceful degradation when the model cannot be loaded at all.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from worker.detector import (
    PERSON_CLASS_ID,
    PersonDetector,
    build_detector,
    resolve_device,
    resolve_model_path,
)


class FakeBoxes:
    def __init__(self, xyxy: list[list[float]], confidences: list[float]) -> None:
        self._xyxy = xyxy
        self._confidences = confidences

    class _Tensor(list):
        def tolist(self):
            return list(self)

    @property
    def xyxy(self):
        return FakeBoxes._Tensor(self._xyxy)

    @property
    def conf(self):
        return FakeBoxes._Tensor(self._confidences)


class FakeResult:
    def __init__(self, boxes: FakeBoxes | None) -> None:
        self.boxes = boxes


class FakeYoloModel:
    """Records every predict() call so tests can assert on what was asked
    for, and returns a scripted result list."""

    def __init__(self, results: list[FakeResult], *, delay_seconds: float = 0.0) -> None:
        self._results = results
        self._delay = delay_seconds
        self.calls: list[dict] = []
        self._concurrent = 0
        self.max_concurrent_observed = 0
        self._lock = threading.Lock()

    def predict(self, source, *, device, classes, conf, verbose):
        with self._lock:
            self._concurrent += 1
            self.max_concurrent_observed = max(self.max_concurrent_observed, self._concurrent)
        self.calls.append({"device": device, "classes": classes, "conf": conf, "verbose": verbose})
        if self._delay:
            time.sleep(self._delay)
        with self._lock:
            self._concurrent -= 1
        return self._results


# --------------------------------------------------------------------------- #
# resolve_device
# --------------------------------------------------------------------------- #
def test_cpu_is_returned_without_needing_cuda():
    assert resolve_device("cpu") == "cpu"


def test_auto_prefers_cuda_when_available(monkeypatch):
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert resolve_device("auto") == "cuda"


def test_auto_falls_back_to_cpu_when_no_cuda(monkeypatch):
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert resolve_device("auto") == "cpu"


def test_explicit_cuda_request_succeeds_when_available(monkeypatch):
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert resolve_device("cuda") == "cuda"


def test_explicit_cuda_request_fails_loudly_when_unavailable(monkeypatch):
    """Not a silent CPU fallback: a machine bought for its GPU should not
    quietly run ten times slower with no explanation."""
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="no CUDA device is available"):
        resolve_device("cuda")


def test_an_unrecognised_value_behaves_like_auto(monkeypatch):
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert resolve_device("nonsense") == "cpu"


# --------------------------------------------------------------------------- #
# PersonDetector.detect
# --------------------------------------------------------------------------- #
def test_detect_converts_yolo_boxes():
    model = FakeYoloModel([FakeResult(FakeBoxes([[10, 20, 30, 40]], [0.91]))])
    detector = PersonDetector(model, device="cpu", confidence_threshold=0.5)

    result = detector.detect("frame")

    assert result.person_count == 1
    box = result.boxes[0]
    assert (box.x1, box.y1, box.x2, box.y2) == (10, 20, 30, 40)
    assert box.confidence == pytest.approx(0.91)
    assert result.inference_ms >= 0


def test_detect_with_no_people_returns_an_empty_result():
    model = FakeYoloModel([FakeResult(FakeBoxes([], []))])
    detector = PersonDetector(model, device="cpu", confidence_threshold=0.5)

    result = detector.detect("frame")

    assert result.person_count == 0
    assert result.boxes == ()


def test_detect_passes_the_person_class_and_confidence_threshold_to_yolo():
    model = FakeYoloModel([FakeResult(FakeBoxes([], []))])
    detector = PersonDetector(model, device="cpu", confidence_threshold=0.73)

    detector.detect("frame")

    call = model.calls[0]
    assert call["classes"] == [PERSON_CLASS_ID]
    assert call["conf"] == pytest.approx(0.73)
    assert call["device"] == "cpu"


def test_detect_handles_a_result_with_no_boxes_object_at_all():
    """ultralytics returns boxes=None when nothing at all was detected in some
    versions/configurations -- must not crash."""
    model = FakeYoloModel([FakeResult(None)])
    detector = PersonDetector(model, device="cpu", confidence_threshold=0.5)

    assert detector.detect("frame").person_count == 0


def test_concurrent_detect_calls_are_serialised():
    """Multiple camera threads share one model; calls must not interleave."""
    model = FakeYoloModel([FakeResult(FakeBoxes([], []))], delay_seconds=0.05)
    detector = PersonDetector(model, device="cpu", confidence_threshold=0.5)

    threads = [threading.Thread(target=detector.detect, args=("frame",)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert model.max_concurrent_observed == 1
    assert len(model.calls) == 5


# --------------------------------------------------------------------------- #
# build_detector
# --------------------------------------------------------------------------- #
def test_build_detector_succeeds_and_warms_up_the_model(monkeypatch):
    model = FakeYoloModel([FakeResult(FakeBoxes([], []))])
    monkeypatch.setattr("ultralytics.YOLO", lambda path: model)

    detector = build_detector("yolo11n.pt", "cpu", 0.5)

    assert detector is not None
    assert detector.device == "cpu"
    assert len(model.calls) == 1  # the warm-up call


def test_build_detector_returns_none_when_the_model_fails_to_load(monkeypatch, caplog):
    def explode(path):
        raise OSError("no internet: could not download weights")

    monkeypatch.setattr("ultralytics.YOLO", explode)

    detector = build_detector("yolo11n.pt", "cpu", 0.5)

    assert detector is None


def test_build_detector_returns_none_rather_than_crash_on_an_unavailable_explicit_gpu(monkeypatch):
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    detector = build_detector("yolo11n.pt", "cuda", 0.5)

    assert detector is None


# --------------------------------------------------------------------------- #
# resolve_model_path
# --------------------------------------------------------------------------- #
def test_a_bare_filename_resolves_into_the_models_dir():
    assert resolve_model_path("yolo11n.pt", "/app/models") == str(Path("/app/models/yolo11n.pt"))


def test_no_models_dir_leaves_the_filename_untouched():
    """Local development: resolve relative to the process's own cwd, exactly
    as ultralytics would without any of this involved."""
    assert resolve_model_path("yolo11n.pt", "") == "yolo11n.pt"


def test_an_absolute_path_is_never_rewritten():
    """An operator supplying their own model knows exactly where they put
    it -- models_dir must not be prepended on top of that."""
    absolute = str(Path("/custom/weights/my-model.pt"))
    assert resolve_model_path(absolute, "/app/models") == absolute


def test_a_url_is_never_rewritten():
    url = "https://example.com/models/custom.pt"
    assert resolve_model_path(url, "/app/models") == url
