"""PersonTracker against the real ultralytics ByteTrack/BoT-SORT
implementations -- these are pure Kalman-filter/IoU math with no model
weights and no network access, so there is no reason to fake them.

The scenarios here are the ones the whole point of tracking rests on: a track
id stays the same as a person moves a little frame to frame, survives a brief
occlusion, and never collides with another camera's ids -- including the
specific bug this module exists to prevent, where constructing a second
tracker resets a process-global id counter and corrupts a first tracker's
already-assigned ids.
"""
from __future__ import annotations

import pytest

from worker.detector import BoundingBox, DetectionResult
from worker.tracker import PersonTracker, _new_tracker


def detection(*boxes: tuple[float, float, float, float, float]) -> DetectionResult:
    """boxes as (x1, y1, x2, y2, confidence) tuples."""
    return DetectionResult(
        boxes=tuple(BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=c) for x1, y1, x2, y2, c in boxes),
        inference_ms=10.0,
    )


def empty_detection() -> DetectionResult:
    return DetectionResult(boxes=(), inference_ms=10.0)


def box_at(x: float, y: float, size: float = 50.0, confidence: float = 0.9):
    return (x, y, x + size, y + size, confidence)


# --------------------------------------------------------------------------- #
# basic association
# --------------------------------------------------------------------------- #
def test_a_stationary_person_keeps_the_same_track_id_across_frames():
    tracker = PersonTracker()

    first = tracker.update(detection(box_at(100, 100)))
    second = tracker.update(detection(box_at(101, 100)))  # ~stationary
    third = tracker.update(detection(box_at(102, 101)))

    assert first.track_count == 1
    ids = {first.boxes[0].track_id, second.boxes[0].track_id, third.boxes[0].track_id}
    assert len(ids) == 1, f"expected one stable track id, got {ids}"


def test_two_people_get_two_distinct_stable_track_ids():
    tracker = PersonTracker()

    first = tracker.update(detection(box_at(50, 50), box_at(500, 500)))
    second = tracker.update(detection(box_at(52, 51), box_at(503, 502)))

    assert first.track_count == 2
    ids_first = {b.track_id for b in first.boxes}
    ids_second = {b.track_id for b in second.boxes}
    assert ids_first == ids_second
    assert len(ids_first) == 2


def test_an_empty_frame_must_still_be_ticked():
    """Skipping update() on a frame with nobody in it would corrupt the
    tracker's internal frame counter, which its occlusion timing depends on."""
    tracker = PersonTracker()
    result = tracker.update(empty_detection())
    assert result.track_count == 0
    assert result.boxes == ()


def test_a_new_person_gets_a_fresh_track_id_not_reused_from_a_departed_one():
    tracker = PersonTracker()

    first = tracker.update(detection(box_at(50, 50)))
    original_id = first.boxes[0].track_id

    # The first person leaves; enough empty frames for the lost track to
    # expire past track_buffer (30 frames).
    for _ in range(35):
        tracker.update(empty_detection())

    # A brand new track is only confirmed (appears in output) on its second
    # consecutive match -- STrack.activate() immediately confirms a track
    # only on the tracker's absolute first frame, as noise suppression for
    # every frame after that. One tick registers it as tentative; the next
    # confirms it.
    tracker.update(detection(box_at(500, 500)))
    second = tracker.update(detection(box_at(501, 501)))
    assert second.boxes[0].track_id != original_id


# --------------------------------------------------------------------------- #
# occlusion recovery -- the actual point of using ByteTrack over naive IoU
# --------------------------------------------------------------------------- #
def test_a_track_survives_a_brief_occlusion():
    tracker = PersonTracker()

    first = tracker.update(detection(box_at(200, 200)))
    original_id = first.boxes[0].track_id

    # A handful of frames with no detection (occluded by another customer,
    # or a momentary miss) -- well within track_buffer=30.
    for _ in range(5):
        tracker.update(empty_detection())

    reappeared = tracker.update(detection(box_at(205, 202)))  # back, roughly where they were
    assert reappeared.boxes[0].track_id == original_id


# --------------------------------------------------------------------------- #
# multi-camera isolation -- the reason PersonTracker is one-instance-per-camera
# --------------------------------------------------------------------------- #
def test_two_tracker_instances_never_collide_on_track_ids():
    camera_a = PersonTracker()
    camera_b = PersonTracker()

    result_a = camera_a.update(detection(box_at(10, 10)))
    result_b = camera_b.update(detection(box_at(10, 10)))  # same coordinates, different camera

    assert result_a.boxes[0].track_id != result_b.boxes[0].track_id


def test_creating_a_second_tracker_does_not_corrupt_the_first_ones_ids():
    """Regression: BYTETracker.__init__ resets a process-global id counter.
    Camera B starting up (or camera A's own tracker being recreated after an
    edit) must not make camera A's next id collide with one it already used."""
    camera_a = PersonTracker()
    first_result = camera_a.update(detection(box_at(10, 10)))
    first_id = first_result.boxes[0].track_id

    # A second tracker is constructed -- e.g. a second camera starting, or
    # this camera's own being rebuilt after a reconfiguration.
    PersonTracker()

    # A brand new person for camera A, unrelated to the first -- must get a
    # fresh id, not one that collides with `first_id`. Two ticks: a new track
    # is only confirmed in output on its second consecutive match once the
    # tracker is past its own absolute first frame (see the identical note in
    # test_a_new_person_gets_a_fresh_track_id_not_reused_from_a_departed_one).
    camera_a.update(detection(box_at(900, 900)))
    second_result = camera_a.update(detection(box_at(901, 901)))
    assert second_result.boxes[0].track_id != first_id


def test_many_tracker_constructions_still_yield_globally_unique_ids():
    trackers = [PersonTracker() for _ in range(10)]
    ids = [t.update(detection(box_at(10, 10))).boxes[0].track_id for t in trackers]
    assert len(set(ids)) == len(ids), f"expected 10 unique ids, got {ids}"


# --------------------------------------------------------------------------- #
# tracker selection
# --------------------------------------------------------------------------- #
def test_botsort_is_selectable_and_functions():
    tracker = PersonTracker(tracker_type="botsort")
    result = tracker.update(detection(box_at(100, 100)))
    assert result.track_count == 1


def test_botsort_never_loads_a_reid_encoder():
    """The one setting that would turn this into an appearance/biometric
    feature (spec §26) -- verified never enabled, not just documented."""
    tracker = PersonTracker(tracker_type="botsort")
    assert tracker._impl.args.with_reid is False  # noqa: SLF001 - white-box check
    assert tracker._impl.encoder is None  # noqa: SLF001


def test_an_unknown_tracker_type_is_rejected():
    with pytest.raises(ValueError, match="bytetrack.*botsort"):
        PersonTracker(tracker_type="nonsense")


# --------------------------------------------------------------------------- #
# failure handling
# --------------------------------------------------------------------------- #
def test_a_malformed_detection_result_does_not_raise():
    """A tracking failure must not be able to take the capture loop down with
    it -- see the identical principle for detection failures in capture.py."""
    tracker = PersonTracker()

    class BrokenDetectionResult:
        boxes = "not a real boxes collection"

    result = tracker.update(BrokenDetectionResult())
    assert result.boxes == ()


# --------------------------------------------------------------------------- #
# _new_tracker directly
# --------------------------------------------------------------------------- #
def test_new_tracker_rejects_an_unknown_type():
    with pytest.raises(ValueError):
        _new_tracker("nonsense")
