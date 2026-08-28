"""Dynamic stay-time colour (spec: Phase 6, "dynamic colour system").

One customer's box on the public display (Phase 7) and their row on the
dashboard's Customers page (Phase 5) must always show the *same* colour for
the *same* stay duration -- so this module is the single Python
implementation of that computation, and `frontend/src/lib/stay-color.ts` is
its exact TypeScript mirror. Neither imports the other (they run in separate
processes/languages); agreement is enforced instead by both test suites
asserting the identical hand-computed vectors -- see that file's own
docstring, and this module's tests, for the shared vector list.

A café's `stay_color_stops` is an ordered list of `{"seconds": int, "color":
"#rrggbb"}` points. Between two consecutive stops, the colour is a plain
linear interpolation of the RGB channels -- continuous, not a jump at a
threshold, per the roadmap's explicit "not discrete buckets." Before the
first stop (impossible once validated, since the first stop is required to
sit at seconds=0) and beyond the last, the colour clamps to that boundary
stop rather than extrapolating past a colour an admin never configured.
"""
from __future__ import annotations

import math
import re
from typing import TypedDict

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ColorStop(TypedDict):
    seconds: int
    color: str


# Traffic-light default: fresh (green) -> 30 minutes (amber) -> 60 minutes
# (red). A café that never touches this setting still gets sensible,
# recognisable behaviour out of the box.
DEFAULT_STAY_COLOR_STOPS: list[ColorStop] = [
    {"seconds": 0, "color": "#22c55e"},
    {"seconds": 1800, "color": "#f59e0b"},
    {"seconds": 3600, "color": "#ef4444"},
]


def default_stay_color_stops() -> list[ColorStop]:
    """A fresh list every call -- Django JSONField defaults must be callables,
    never a shared mutable literal that every unconfigured café would alias."""
    return [dict(stop) for stop in DEFAULT_STAY_COLOR_STOPS]


def validate_color_stops(value: object) -> None:
    """Validates the shape `color_for_duration` below relies on completely --
    that function does no further checking of its own, so nothing malformed
    may reach it. Raised as a plain ValidationError so it plugs directly into
    a Django model field's `validators=`."""
    if not isinstance(value, list) or len(value) < 2:
        raise ValidationError(
            _("stay_color_stops must be a list of at least two stops."),
            code="color_stops_too_short",
        )

    previous_seconds: int | None = None
    for index, stop in enumerate(value):
        if not isinstance(stop, dict) or set(stop) != {"seconds", "color"}:
            raise ValidationError(
                _("Each stop must be an object with exactly 'seconds' and 'color'."),
                code="color_stop_bad_shape",
            )

        seconds = stop["seconds"]
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
            raise ValidationError(
                _("Stop %(index)s: 'seconds' must be a non-negative integer."),
                code="color_stop_bad_seconds",
                params={"index": index},
            )
        if index == 0 and seconds != 0:
            raise ValidationError(
                _("The first stop must start at seconds=0, so every duration has a colour."),
                code="color_stops_must_start_at_zero",
            )
        if previous_seconds is not None and seconds <= previous_seconds:
            raise ValidationError(
                _("Stop %(index)s: 'seconds' must strictly increase from the previous stop."),
                code="color_stops_not_increasing",
                params={"index": index},
            )
        previous_seconds = seconds

        color = stop["color"]
        if not isinstance(color, str) or not HEX_COLOR_RE.match(color):
            raise ValidationError(
                _("Stop %(index)s: 'color' must be a 6-digit hex colour like #22c55e."),
                code="color_stop_bad_color",
                params={"index": index},
            )


def color_for_duration(seconds: float, stops: list[ColorStop]) -> str:
    """The colour for a stay of `seconds`, per `stops` (already validated).

    `stops` must be sorted by `seconds` ascending with the first at 0 --
    exactly what `validate_color_stops` enforces on anything stored in
    `Cafe.stay_color_stops`, so this function trusts that shape rather than
    re-deriving it.
    """
    if seconds <= stops[0]["seconds"]:
        return stops[0]["color"]

    for lower, upper in zip(stops, stops[1:], strict=False):
        if seconds <= upper["seconds"]:
            span = upper["seconds"] - lower["seconds"]
            t = (seconds - lower["seconds"]) / span if span else 0.0
            return _mix(lower["color"], upper["color"], t)

    return stops[-1]["color"]


def _mix(color_a: str, color_b: str, t: float) -> str:
    a = _hex_to_rgb(color_a)
    b = _hex_to_rgb(color_b)
    # Round-half-up, not Python's banker's-rounding `round()` -- the
    # TypeScript mirror uses Math.round(), which always rounds .5 up for a
    # non-negative number. Channel values are always non-negative, so this
    # keeps the two implementations bit-for-bit identical at every t instead
    # of merely close.
    mixed = tuple(math.floor(a[i] + (b[i] - a[i]) * t + 0.5) for i in range(3))
    return _rgb_to_hex(mixed)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in rgb)
