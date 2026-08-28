"""Zone-crossing geometry and detector logic.

This module is the crux of Phase 5's correctness: a bug here silently
corrupts every stay-time measurement downstream, so the geometry primitives
are tested directly and in isolation before the detector is tested on top of
them.
"""
from __future__ import annotations

from worker.tracker import TrackedBox, TrackingResult
from worker.zones import (
    ZoneConfig,
    ZoneCrossingDetector,
    reference_point,
    segments_intersect,
    side_of_line,
)


def box(track_id: int, x1: float, y1: float, x2: float, y2: float, confidence: float = 0.9) -> TrackedBox:
    return TrackedBox(track_id=track_id, x1=x1, y1=y1, x2=x2, y2=y2, confidence=confidence)


def tick(*boxes: TrackedBox) -> TrackingResult:
    return TrackingResult(boxes=tuple(boxes))


# A vertical entrance line at x=100, spanning y in [0, 200]. With
# entry_is_positive_side=True: walking so x decreases (ending left of the
# line, the positive side per side_of_line's sign convention) is an entry;
# walking so x increases (ending right, negative side) is an exit.
DOORWAY = ZoneConfig(id="z1", name="Front door", point_a=(100, 0), point_b=(100, 200), entry_is_positive_side=True)


# --------------------------------------------------------------------------- #
# geometry primitives
# --------------------------------------------------------------------------- #
def test_reference_point_is_bottom_centre():
    assert reference_point(box(1, 10, 20, 30, 40)) == (20.0, 40.0)


def test_side_of_line_sign_convention():
    a, b = (100, 0), (100, 200)
    assert side_of_line((50, 100), a, b) > 0  # left of the line
    assert side_of_line((150, 100), a, b) < 0  # right of the line
    assert side_of_line((100, 100), a, b) == 0  # exactly on the line


def test_segments_intersect_when_they_cross():
    assert segments_intersect((50, 100), (150, 100), (100, 0), (100, 200)) is True


def test_segments_do_not_intersect_when_parallel_and_apart():
    assert segments_intersect((50, 100), (150, 100), (50, 500), (150, 500)) is False


def test_segments_do_not_intersect_beyond_the_finite_zone_segment():
    """Crosses the *infinite* extension of the zone line, but nowhere near
    the actual configured doorway -- must not count."""
    assert segments_intersect((50, 900), (150, 900), (100, 0), (100, 200)) is False


def test_collinear_overlapping_segments_intersect():
    assert segments_intersect((100, 50), (100, 150), (100, 0), (100, 200)) is True


def test_collinear_non_overlapping_segments_do_not_intersect():
    assert segments_intersect((100, 300), (100, 400), (100, 0), (100, 200)) is False


# --------------------------------------------------------------------------- #
# ZoneCrossingDetector: basic crossings
# --------------------------------------------------------------------------- #
def test_first_sighting_produces_no_crossing():
    """Nothing to compare the very first position against."""
    detector = ZoneCrossingDetector([DOORWAY])
    crossings = detector.update(tick(box(1, 45, 90, 55, 110)))  # centre (50, 110)
    assert crossings == []


def test_walking_right_to_left_is_an_entry():
    detector = ZoneCrossingDetector([DOORWAY])
    detector.update(tick(box(1, 145, 90, 155, 110)))  # reference point (150, 110): right of the line
    crossings = detector.update(tick(box(1, 45, 90, 55, 110)))  # reference point (50, 110): now left

    assert len(crossings) == 1
    event = crossings[0]
    assert event.track_id == 1
    assert event.zone_id == "z1"
    assert event.zone_name == "Front door"
    assert event.direction == "entry"
    assert (event.x, event.y) == (50.0, 110.0)


def test_walking_left_to_right_is_an_exit():
    detector = ZoneCrossingDetector([DOORWAY])
    detector.update(tick(box(1, 45, 90, 55, 110)))
    crossings = detector.update(tick(box(1, 145, 90, 155, 110)))

    assert len(crossings) == 1
    assert crossings[0].direction == "exit"


def test_the_direction_convention_can_be_flipped():
    """The same physical movement, opposite convention, opposite label."""
    reversed_doorway = ZoneConfig(
        id="z1", name="Front door", point_a=(100, 0), point_b=(100, 200), entry_is_positive_side=False
    )
    detector = ZoneCrossingDetector([reversed_doorway])
    detector.update(tick(box(1, 145, 90, 155, 110)))
    crossings = detector.update(tick(box(1, 45, 90, 55, 110)))

    assert crossings[0].direction == "exit"  # was "entry" with the un-reversed convention


def test_staying_on_the_same_side_produces_no_crossing():
    detector = ZoneCrossingDetector([DOORWAY])
    detector.update(tick(box(1, 15, 90, 25, 110)))
    crossings = detector.update(tick(box(1, 25, 90, 35, 110)))  # moved, but stayed left of x=100
    assert crossings == []


def test_movement_along_the_lines_extension_is_not_a_crossing():
    """Crosses the infinite line at a point far outside the configured
    door -- someone walking down a hallway well away from the entrance."""
    detector = ZoneCrossingDetector([DOORWAY])
    detector.update(tick(box(1, 45, 890, 55, 910)))  # (50, 910): y=910, well beyond [0,200]
    crossings = detector.update(tick(box(1, 145, 890, 155, 910)))
    assert crossings == []


def test_landing_exactly_on_the_line_is_not_treated_as_a_crossing():
    detector = ZoneCrossingDetector([DOORWAY])
    detector.update(tick(box(1, 45, 90, 55, 110)))
    crossings = detector.update(tick(box(1, 95, 90, 105, 110)))  # centre exactly (100, 110)
    assert crossings == []


# --------------------------------------------------------------------------- #
# multiple zones and multiple people
# --------------------------------------------------------------------------- #
def test_a_movement_is_checked_against_every_configured_zone():
    side_door = ZoneConfig(id="z2", name="Side door", point_a=(500, 0), point_b=(500, 200), entry_is_positive_side=True)
    detector = ZoneCrossingDetector([DOORWAY, side_door])

    detector.update(tick(box(1, 145, 90, 155, 110)))  # right of the front door only
    crossings = detector.update(tick(box(1, 45, 90, 55, 110)))  # crosses the front door, not the side door

    assert len(crossings) == 1
    assert crossings[0].zone_id == "z1"


def test_two_people_crossing_the_same_tick_are_both_attributed_correctly():
    detector = ZoneCrossingDetector([DOORWAY])
    detector.update(
        tick(
            box(1, 145, 90, 155, 110),  # will enter
            box(2, 45, 90, 55, 110),  # will exit
        )
    )
    crossings = detector.update(
        tick(
            box(1, 45, 90, 55, 110),
            box(2, 145, 90, 155, 110),
        )
    )

    by_track = {c.track_id: c.direction for c in crossings}
    assert by_track == {1: "entry", 2: "exit"}


# --------------------------------------------------------------------------- #
# occlusion tolerance and staleness
# --------------------------------------------------------------------------- #
def test_a_crossing_is_still_detected_after_the_track_is_briefly_absent():
    """A person occluded exactly as they step through the doorway: the track
    id survives in PersonTracker, but this tick's TrackingResult simply has no
    box for them. Their pre-occlusion position must still be on record when
    they reappear on the other side."""
    detector = ZoneCrossingDetector([DOORWAY])
    detector.update(tick(box(1, 145, 90, 155, 110)))  # seen, right of the line
    detector.update(tick())  # occluded: absent this tick
    detector.update(tick())  # still occluded
    crossings = detector.update(tick(box(1, 45, 90, 55, 110)))  # reappears, left of the line

    assert len(crossings) == 1
    assert crossings[0].direction == "entry"


def test_position_history_is_pruned_after_the_staleness_window():
    """Once a track has genuinely been gone long enough, its old position
    must not be used to manufacture a crossing when a *new* track later
    reuses -- well, never reuses an id, but the pruning itself is what is
    under test here: a very old position must not silently linger forever."""
    detector = ZoneCrossingDetector([DOORWAY])
    detector.update(tick(box(1, 145, 90, 155, 110)))

    for _ in range(ZoneCrossingDetector.STALE_AFTER_TICKS + 1):
        detector.update(tick())  # ticks continue to advance while track 1 is absent

    # Track 1 "reappears" (in reality this would be a fresh id; testing the
    # same id here specifically to prove the stale position was discarded).
    crossings = detector.update(tick(box(1, 45, 90, 55, 110)))
    assert crossings == []  # treated as a first sighting, not a crossing


def test_empty_ticks_still_advance_the_staleness_clock():
    """update() must be called every tick, including empty ones, for pruning
    timing to be meaningful at all -- mirrors the identical requirement on
    PersonTracker.update()."""
    detector = ZoneCrossingDetector([DOORWAY])
    detector.update(tick(box(1, 145, 90, 155, 110)))

    for _ in range(ZoneCrossingDetector.STALE_AFTER_TICKS + 1):
        detector.update(tick())

    assert 1 not in detector._last_position  # noqa: SLF001 - white-box check
