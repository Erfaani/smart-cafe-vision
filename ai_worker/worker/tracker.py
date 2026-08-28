"""Anonymous multi-object tracking on top of Phase 3 detections.

ByteTrack by default, with BoT-SORT available as an alternative -- both built
on ultralytics' own tracker implementations rather than reimplementing one.
Association is motion-and-IoU only. BoT-SORT's optional appearance/ReID mode
is never enabled here: that mode extracts an embedding that functions as a
biometric feature, which spec §26 rules out. Nothing in this module reads or
stores anything beyond a box, a confidence, and a small integer id.

**Why not ultralytics' `Model.track()` convenience API.** It ties tracker
state to `predictor.trackers`, a list indexed by *video-stream position*, on
the shared model object. This project shares one YOLO model across every
camera for detection (worker/detector.py) -- routing per-camera tracking
state through that same shared, positionally-indexed list would conflate
different cameras' tracks the moment their detection ticks interleave, which
they always do with independent capture threads. So each camera owns one
independent `PersonTracker`, fed by the shared detector's plain
`DetectionResult` output through a small duck-typed shim -- ultralytics'
tracker classes only ever read `.xywh`, `.conf`, `.cls` and boolean-index
slicing off whatever object they are given (see
`ultralytics.trackers.utils.stracks.parse_bboxes`), so a real ultralytics
`Boxes`/`Results` object is never required.

**Track ids are process-global, not per-camera**, by ultralytics' own design
(`BaseTrack._count` is a class-level counter) -- so two cameras' tracks never
collide, and no camera prefix needs to be added on top. The one hazard that
design creates: `BYTETracker.__init__` unconditionally resets that global
counter to zero, so naively constructing a *second* tracker (a second camera
starting, or one camera's tracker being recreated after an edit) would
corrupt id uniqueness for every other camera already running. `_new_tracker`
below is the one place that construction happens, and it restores the counter
immediately afterward -- see its docstring.
"""
from __future__ import annotations

import logging
import types
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger("scv.worker.tracker")

TrackerType = str  # "bytetrack" | "botsort"

# Mirrors ultralytics/cfg/trackers/{bytetrack,botsort}.yaml. Kept here rather
# than loaded from those files so this module has no filesystem dependency
# and so `with_reid` can never silently become configurable -- it is not a
# field a caller of this module can set at all.
_TRACKER_ARGS: dict[TrackerType, dict[str, Any]] = {
    "bytetrack": {
        "tracker_type": "bytetrack",
        "track_high_thresh": 0.25,
        "track_low_thresh": 0.1,
        "new_track_thresh": 0.25,
        "track_buffer": 30,
        "match_thresh": 0.8,
        "fuse_score": True,
    },
    "botsort": {
        "tracker_type": "botsort",
        "track_high_thresh": 0.25,
        "track_low_thresh": 0.1,
        "new_track_thresh": 0.25,
        "track_buffer": 30,
        "match_thresh": 0.8,
        "fuse_score": True,
        "gmc_method": "sparseOptFlow",
        "proximity_thresh": 0.5,
        "appearance_thresh": 0.8,
        "with_reid": False,  # never enabled -- see module docstring
        "model": "auto",
    },
}


@dataclass(frozen=True, slots=True)
class TrackedBox:
    track_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float


@dataclass(frozen=True, slots=True)
class TrackingResult:
    boxes: tuple[TrackedBox, ...]

    @property
    def track_count(self) -> int:
        return len(self.boxes)


class _DetectionsView:
    """Duck-typed stand-in for the `results` argument ultralytics' trackers
    expect: exposes `.xywh`, `.conf`, `.cls` as arrays, supports `len()`, and
    supports boolean-mask `__getitem__` (the trackers slice detections into
    high/low confidence subsets via `results[mask]` internally). Built from
    this project's own `DetectionResult`; never wraps a real ultralytics
    `Boxes` object.
    """

    __slots__ = ("xywh", "conf", "cls")

    def __init__(self, xywh: np.ndarray, conf: np.ndarray, cls: np.ndarray) -> None:
        self.xywh = xywh
        self.conf = conf
        self.cls = cls

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, mask: np.ndarray) -> _DetectionsView:
        return _DetectionsView(self.xywh[mask], self.conf[mask], self.cls[mask])


def _to_detections_view(detection_result: Any) -> _DetectionsView:
    boxes = detection_result.boxes
    if not boxes:
        empty = np.zeros((0, 4), dtype=np.float32)
        return _DetectionsView(empty, np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.float32))

    xywh = np.array(
        [[(b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2, b.x2 - b.x1, b.y2 - b.y1] for b in boxes],
        dtype=np.float32,
    )
    conf = np.array([b.confidence for b in boxes], dtype=np.float32)
    # Single-class tracking (person only, enforced upstream by the detector's
    # own class filter): the class array only needs to be present and uniform.
    cls = np.zeros(len(boxes), dtype=np.float32)
    return _DetectionsView(xywh, conf, cls)


def _new_tracker(tracker_type: TrackerType):
    """Construct one ultralytics tracker instance without corrupting the
    global track-id counter every other camera's tracker shares.

    `BYTETracker.__init__` (which `BOTSORT.__init__` also calls via `super()`)
    unconditionally calls `reset_id()`, zeroing `BaseTrack._count`. That is
    fine for the *first* tracker created in the process; it is data
    corruption for every subsequent one, since a camera being added or a
    camera's tracker being recreated after an edit must not be able to make
    an already-running camera's next track id collide with one of its
    earlier, still-remembered ids. The counter is preserved and restored
    around construction rather than re-implementing `__init__` by hand, so
    this stays correct even if ultralytics adds fields to it in a future
    version.
    """
    if tracker_type not in _TRACKER_ARGS:
        raise ValueError(f"Unknown tracker_type {tracker_type!r}; expected 'bytetrack' or 'botsort'.")

    from ultralytics.trackers.basetrack import BaseTrack
    from ultralytics.trackers.bot_sort import BOTSORT
    from ultralytics.trackers.byte_tracker import BYTETracker

    impl_cls = BOTSORT if tracker_type == "botsort" else BYTETracker
    args = types.SimpleNamespace(**_TRACKER_ARGS[tracker_type])

    preserved_count = BaseTrack._count
    tracker = impl_cls(args)
    BaseTrack._count = preserved_count
    return tracker


class PersonTracker:
    """Owns one tracker's state for exactly one camera's stream.

    Not shared across cameras and not thread-safe by design: a single camera's
    capture thread is the only caller, matching how CameraCaptureWorker already
    owns everything else about that camera's state (see worker/capture.py).
    """

    def __init__(self, tracker_type: TrackerType = "bytetrack") -> None:
        self.tracker_type = tracker_type
        self._impl = _new_tracker(tracker_type)

    def update(self, detection_result: Any, frame: object = None) -> TrackingResult:
        """Associate this tick's detections with existing tracks.

        Must be called every detection tick, including ticks with zero
        detections -- skipping calls (e.g. only calling it when someone is
        present) would silently corrupt the tracker's internal frame counter,
        which its occlusion/lost-track timing depends on.
        """
        try:
            view = _to_detections_view(detection_result)
            rows = self._impl.update(view, frame)
        except Exception:
            logger.exception("tracker_update_failed tracker_type=%s", self.tracker_type)
            return TrackingResult(boxes=())

        boxes = tuple(
            TrackedBox(
                track_id=int(row[4]),
                x1=float(row[0]),
                y1=float(row[1]),
                x2=float(row[2]),
                y2=float(row[3]),
                confidence=float(row[5]),
            )
            for row in rows
        )
        return TrackingResult(boxes=boxes)
