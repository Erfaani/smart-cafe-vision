"""Table occupancy geometry and detector logic."""
from __future__ import annotations

from worker.tables import TableOccupancyDetector, TableZoneConfig, _clip, _union_area
from worker.tracker import TrackedBox, TrackingResult


def box(track_id: int, x1: float, y1: float, x2: float, y2: float, confidence: float = 0.9) -> TrackedBox:
    return TrackedBox(track_id=track_id, x1=x1, y1=y1, x2=x2, y2=y2, confidence=confidence)


def tick(*boxes: TrackedBox) -> TrackingResult:
    return TrackingResult(boxes=tuple(boxes))


# A 100x100 table at (0,0)-(100,100).
TABLE = TableZoneConfig(id="t1", name="Table 1", x1=0, y1=0, x2=100, y2=100)


# --------------------------------------------------------------------------- #
# geometry primitives
# --------------------------------------------------------------------------- #
def test_clip_returns_the_overlap_rectangle():
    assert _clip(box(1, 50, 50, 150, 150), TABLE) == (50, 50, 100, 100)


def test_clip_returns_none_when_boxes_dont_overlap():
    assert _clip(box(1, 200, 200, 300, 300), TABLE) is None


def test_clip_returns_none_for_edge_touching_boxes():
    """Touching at a single edge is zero area -- not a meaningful overlap."""
    assert _clip(box(1, 100, 0, 200, 100), TABLE) is None


def test_union_area_of_a_single_rect_is_its_own_area():
    assert _union_area([(0, 0, 10, 10)]) == 100


def test_union_area_of_non_overlapping_rects_is_the_sum():
    assert _union_area([(0, 0, 10, 10), (20, 20, 30, 30)]) == 200


def test_union_area_of_overlapping_rects_does_not_double_count():
    # Two 10x10 squares overlapping in a 5x10 strip: 100 + 100 - 50 = 150.
    assert _union_area([(0, 0, 10, 10), (5, 0, 15, 10)]) == 150


def test_union_area_of_no_rects_is_zero():
    assert _union_area([]) == 0.0


# --------------------------------------------------------------------------- #
# TableOccupancyDetector
# --------------------------------------------------------------------------- #
def test_table_becomes_occupied_after_confirm_ticks_of_sufficient_overlap():
    detector = TableOccupancyDetector([TABLE])
    covering = box(1, 0, 0, 100, 100)  # fully covers the table

    events = []
    for _ in range(TableOccupancyDetector.CONFIRM_TICKS):
        events = detector.update(tick(covering))

    assert events == [(TABLE.id, TABLE.name, "occupied")] or events[-1].event == "occupied"
    assert detector.occupied_table_ids() == ["t1"]


def test_a_single_covered_tick_is_not_enough():
    detector = TableOccupancyDetector([TABLE])
    covering = box(1, 0, 0, 100, 100)

    events = detector.update(tick(covering))

    assert events == []
    assert detector.occupied_table_ids() == []


def test_a_person_briefly_passing_by_does_not_confirm_occupancy():
    detector = TableOccupancyDetector([TABLE])
    covering = box(1, 0, 0, 100, 100)

    for _ in range(TableOccupancyDetector.CONFIRM_TICKS - 1):
        detector.update(tick(covering))
    events = detector.update(tick())  # the person is gone before confirmation

    assert events == []
    assert detector.occupied_table_ids() == []


def test_table_becomes_released_after_release_ticks_of_no_overlap():
    detector = TableOccupancyDetector([TABLE])
    covering = box(1, 0, 0, 100, 100)
    for _ in range(TableOccupancyDetector.CONFIRM_TICKS):
        detector.update(tick(covering))
    assert detector.occupied_table_ids() == ["t1"]

    events = []
    for _ in range(TableOccupancyDetector.RELEASE_TICKS):
        events = detector.update(tick())

    assert events[-1].event == "released"
    assert detector.occupied_table_ids() == []


def test_brief_gap_does_not_release_an_occupied_table():
    detector = TableOccupancyDetector([TABLE])
    covering = box(1, 0, 0, 100, 100)
    for _ in range(TableOccupancyDetector.CONFIRM_TICKS):
        detector.update(tick(covering))

    for _ in range(TableOccupancyDetector.RELEASE_TICKS - 1):
        events = detector.update(tick())
        assert events == []  # not released yet

    events = detector.update(tick(covering))  # covered again before release confirms
    assert events == []
    assert detector.occupied_table_ids() == ["t1"]


def test_overlap_below_the_threshold_never_confirms_occupancy():
    detector = TableOccupancyDetector([TABLE])
    # A tiny sliver overlap, well under OVERLAP_FRACTION_THRESHOLD.
    sliver = box(1, 0, 0, 5, 5)

    for _ in range(TableOccupancyDetector.CONFIRM_TICKS + 2):
        detector.update(tick(sliver))

    assert detector.occupied_table_ids() == []


def test_two_people_jointly_cover_a_table_neither_covers_alone():
    """Two non-overlapping slivers, each below OVERLAP_FRACTION_THRESHOLD
    (8% of the table) alone, whose union clears it (16% combined)."""
    detector = TableOccupancyDetector([TABLE])
    a = box(1, 0, 0, 8, 100)
    b = box(2, 92, 0, 100, 100)

    for _ in range(TableOccupancyDetector.CONFIRM_TICKS):
        detector.update(tick(a, b))

    assert detector.occupied_table_ids() == ["t1"]


def test_multiple_tables_are_tracked_independently():
    table_2 = TableZoneConfig(id="t2", name="Table 2", x1=200, y1=200, x2=300, y2=300)
    detector = TableOccupancyDetector([TABLE, table_2])
    covering_table_1 = box(1, 0, 0, 100, 100)

    for _ in range(TableOccupancyDetector.CONFIRM_TICKS):
        detector.update(tick(covering_table_1))

    assert detector.occupied_table_ids() == ["t1"]


def test_no_boxes_at_all_never_confirms_occupancy():
    detector = TableOccupancyDetector([TABLE])
    for _ in range(TableOccupancyDetector.CONFIRM_TICKS + 5):
        events = detector.update(tick())
    assert events == []
    assert detector.occupied_table_ids() == []
