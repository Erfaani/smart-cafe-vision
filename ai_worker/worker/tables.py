"""Table occupancy detection (spec §10).

A table is modelled as a rectangle on the camera's frame -- an area to be
covered, not a line to be crossed (see backend/apps/cameras/models.py's
`TableZone` docstring for why this is a genuinely different shape from
worker/zones.py's entrance/exit lines, and its own model rather than a
forced generalisation of one).

Occupancy is a box-overlap heuristic, deliberately: a tracked person's
detected box mostly shows their upper body once seated (furniture occludes
the rest), so there is no reliable "reference point" the way
worker/zones.py has one for a standing, walking person. Rather than invent a
false-precision "occupancy point", this asks a coarser, more honest
question -- does a meaningful fraction of the table's area overlap with
someone's tracked box -- which is exactly why the spec is upfront that an
overhead camera gives reliable table occupancy and a wall-mounted one gives
an approximation (backend/apps/cameras/models.py's `Camera.mount_type`).

Debounced in both directions, independently of how many ticks a detection
took (spec §22, same principle as ZoneCrossingDetector): a table needs
`CONFIRM_TICKS` consecutive covered ticks to become OCCUPIED (so someone
briefly reaching across it does not count) and `RELEASE_TICKS` consecutive
uncovered ticks to become free again (so one bad detection frame, or someone
standing up for a moment, does not flicker the table's status).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from worker.tracker import TrackedBox, TrackingResult

logger = logging.getLogger("scv.worker.tables")

Rect = tuple[float, float, float, float]  # x1, y1, x2, y2


@dataclass(frozen=True, slots=True)
class TableZoneConfig:
    """One table's rectangle, as configured by a café admin."""

    id: str
    name: str
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)


@dataclass(frozen=True, slots=True)
class TableOccupancyEvent:
    table_id: str
    table_name: str
    event: Literal["occupied", "released"]


def _clip(box: TrackedBox, table: TableZoneConfig) -> Rect | None:
    """The overlapping rectangle between a tracked box and a table, or None
    if they do not overlap at all."""
    x1 = max(box.x1, table.x1)
    y1 = max(box.y1, table.y1)
    x2 = min(box.x2, table.x2)
    y2 = min(box.y2, table.y2)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _union_area(rects: list[Rect]) -> float:
    """Exact union area of a small set of (possibly overlapping) rectangles,
    via coordinate compression -- more than one person can be seated at the
    same table, and their individual overlaps should not double-count where
    they overlap each other. Always called with a handful of rectangles (the
    boxes overlapping one table), so the O(n^2) grid this builds costs
    nothing real."""
    if not rects:
        return 0.0

    xs = sorted({x for rect in rects for x in (rect[0], rect[2])})
    ys = sorted({y for rect in rects for y in (rect[1], rect[3])})

    total = 0.0
    for i in range(len(xs) - 1):
        cell_x1, cell_x2 = xs[i], xs[i + 1]
        width = cell_x2 - cell_x1
        if width <= 0:
            continue
        cell_cx = (cell_x1 + cell_x2) / 2
        for j in range(len(ys) - 1):
            cell_y1, cell_y2 = ys[j], ys[j + 1]
            height = cell_y2 - cell_y1
            if height <= 0:
                continue
            cell_cy = (cell_y1 + cell_y2) / 2
            if any(r[0] <= cell_cx <= r[2] and r[1] <= cell_cy <= r[3] for r in rects):
                total += width * height
    return total


@dataclass(slots=True)
class _TableState:
    occupied: bool = False
    consecutive_covered: int = 0
    consecutive_uncovered: int = 0


class TableOccupancyDetector:
    """Owns occupancy state for one camera's tables.

    One instance per camera, same reasoning as PersonTracker and
    ZoneCrossingDetector: state here is per-camera by construction, and there
    is nothing to share across cameras.
    """

    OVERLAP_FRACTION_THRESHOLD = 0.15
    CONFIRM_TICKS = 3
    RELEASE_TICKS = 5

    def __init__(self, tables: list[TableZoneConfig]) -> None:
        self._tables = tables
        self._state: dict[str, _TableState] = {table.id: _TableState() for table in tables}

    def update(self, tracking: TrackingResult) -> list[TableOccupancyEvent]:
        """Must be called every tracking tick, including empty ones, to keep
        the debounce counters correct."""
        events: list[TableOccupancyEvent] = []

        for table in self._tables:
            state = self._state[table.id]
            covered = self._overlap_fraction(table, tracking.boxes) >= self.OVERLAP_FRACTION_THRESHOLD

            if covered:
                state.consecutive_covered += 1
                state.consecutive_uncovered = 0
            else:
                state.consecutive_uncovered += 1
                state.consecutive_covered = 0

            if not state.occupied and state.consecutive_covered >= self.CONFIRM_TICKS:
                state.occupied = True
                events.append(TableOccupancyEvent(table.id, table.name, "occupied"))
            elif state.occupied and state.consecutive_uncovered >= self.RELEASE_TICKS:
                state.occupied = False
                events.append(TableOccupancyEvent(table.id, table.name, "released"))

        return events

    def occupied_table_ids(self) -> list[str]:
        """The confirmed-occupied roster, for camera_stats' heartbeat --
        exactly the active_track_ids pattern in worker/capture.py, so a
        backend closer can notice a table whose worker went quiet without
        ever seeing a "released" event."""
        return [table.id for table in self._tables if self._state[table.id].occupied]

    def _overlap_fraction(self, table: TableZoneConfig, boxes: list[TrackedBox]) -> float:
        if table.area <= 0:
            return 0.0
        clipped = [rect for box in boxes if (rect := _clip(box, table)) is not None]
        return _union_area(clipped) / table.area
