"""Entrance/exit line crossing detection.

A café entrance is modelled as a directed line segment on the camera's frame:
two points, and a side. When a tracked person's reference point moves from one
side of the line to the other *and* their path actually crosses the finite
segment (not just its infinite extension), that is a crossing -- direction
determined by which side they started on.

The reference point is the bottom-centre of each tracked box, not its
centroid: it best approximates where a person is actually standing on the
ground plane, which is what matters for a threshold crossing (a tall person
leaning through a doorway has a centroid that crosses well before their feet
do).

Deliberately independent of how many ticks elapsed: section 22's "do not
assume camera FPS = AI FPS" applies here too. What matters is which side of
the line a track was on *last recorded tick* versus *this tick* -- not how
many frames passed in between, and not how many ticks the camera has been
running. A person who crosses while briefly occluded (PersonTracker keeps
their track id through a brief occlusion; see worker/tracker.py) is still
correctly detected the moment they reappear on the other side, because their
pre-occlusion position is still on record.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from worker.tracker import TrackingResult

logger = logging.getLogger("scv.worker.zones")

Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class ZoneConfig:
    """One entrance/exit line, as configured by a café admin."""

    id: str
    name: str
    point_a: Point
    point_b: Point
    # A crossing from the negative side to the positive side of the directed
    # line point_a -> point_b counts as an entry when True, an exit when
    # False. See side_of_line for the sign convention.
    entry_is_positive_side: bool = True


@dataclass(frozen=True, slots=True)
class CrossingEvent:
    track_id: int
    zone_id: str
    zone_name: str
    direction: str  # "entry" | "exit"
    x: float
    y: float


def reference_point(box) -> Point:
    """Bottom-centre of a tracked box -- see module docstring for why."""
    return ((box.x1 + box.x2) / 2.0, box.y2)


def side_of_line(point: Point, a: Point, b: Point) -> float:
    """Signed area of the triangle (a, b, point), doubled.

    Positive when `point` is to the left of the directed line a->b, negative
    to the right, zero exactly on the line. The standard 2D cross product
    test, and the one place the "which side is inside" convention lives.
    """
    return (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])


def _orientation(a: Point, b: Point, c: Point) -> int:
    value = side_of_line(c, a, b)
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _on_segment(p: Point, q: Point, r: Point) -> bool:
    """True when q lies on the segment p-r, given p, q, r are already known
    to be collinear."""
    return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])


def segments_intersect(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """Standard orientation-based segment-segment intersection test.

    Used so a person walking near the *extension* of an entrance line, but
    nowhere close to the actual doorway, is never counted -- only a path that
    crosses the finite configured segment counts.
    """
    o1 = _orientation(p1, p2, p3)
    o2 = _orientation(p1, p2, p4)
    o3 = _orientation(p3, p4, p1)
    o4 = _orientation(p3, p4, p2)

    if o1 != o2 and o3 != o4:
        return True

    # Collinear special cases: the movement segment runs exactly along the
    # zone line. Rare with real pixel coordinates, but a real crossing must
    # not be silently missed because of it.
    if o1 == 0 and _on_segment(p1, p3, p2):
        return True
    if o2 == 0 and _on_segment(p1, p4, p2):
        return True
    if o3 == 0 and _on_segment(p3, p1, p4):
        return True
    if o4 == 0 and _on_segment(p3, p2, p4):
        return True
    return False


class ZoneCrossingDetector:
    """Owns crossing state for one camera's zones, across its tracked people.

    One instance per camera, like PersonTracker -- a track id is only ever
    meaningful within the camera that produced it, so there is nothing to
    share across cameras here either.
    """

    # Position history for a track is dropped after this many update() calls
    # without seeing it. Generous on purpose: PersonTracker's own occlusion
    # tolerance (its track_buffer, evaluated in frames far below this tick
    # cadence) is much shorter, so any track PersonTracker is still willing to
    # call "the same person" always still has fresh history here. This bound
    # exists only to eventually forget people who have genuinely left for
    # good -- unbounded retention would leak memory over a full café day with
    # thousands of distinct track ids passing through.
    STALE_AFTER_TICKS = 300

    def __init__(self, zones: list[ZoneConfig]) -> None:
        self._zones = zones
        self._last_position: dict[int, Point] = {}
        self._last_seen_tick: dict[int, int] = {}
        self._tick = 0

    def update(self, tracking: TrackingResult) -> list[CrossingEvent]:
        """Must be called every tracking tick, including empty ticks, to keep
        the staleness clock correct -- same requirement as PersonTracker.update()."""
        self._tick += 1
        crossings: list[CrossingEvent] = []

        for box in tracking.boxes:
            point = reference_point(box)
            last = self._last_position.get(box.track_id)

            if last is not None:
                for zone in self._zones:
                    crossing = self._check_zone(zone, box.track_id, last, point)
                    if crossing is not None:
                        crossings.append(crossing)

            self._last_position[box.track_id] = point
            self._last_seen_tick[box.track_id] = self._tick

        self._prune_stale()
        return crossings

    def _check_zone(
        self, zone: ZoneConfig, track_id: int, last: Point, point: Point
    ) -> CrossingEvent | None:
        side_before = side_of_line(last, zone.point_a, zone.point_b)
        side_after = side_of_line(point, zone.point_a, zone.point_b)

        if side_before == 0 or side_after == 0:
            # Landed exactly on the line: not a meaningful direction signal on
            # its own, and guessing risks a spurious event from a single-pixel
            # coincidence. Astronomically rare with real detection coordinates.
            return None
        if (side_before > 0) == (side_after > 0):
            return None  # stayed on the same side
        if not segments_intersect(last, point, zone.point_a, zone.point_b):
            return None  # crossed the infinite line, but nowhere near the door

        crossed_to_positive = side_after > 0
        is_entry = crossed_to_positive == zone.entry_is_positive_side
        return CrossingEvent(
            track_id=track_id,
            zone_id=zone.id,
            zone_name=zone.name,
            direction="entry" if is_entry else "exit",
            x=point[0],
            y=point[1],
        )

    def _prune_stale(self) -> None:
        stale = [
            track_id
            for track_id, seen_at in self._last_seen_tick.items()
            if self._tick - seen_at > self.STALE_AFTER_TICKS
        ]
        for track_id in stale:
            self._last_position.pop(track_id, None)
            self._last_seen_tick.pop(track_id, None)
