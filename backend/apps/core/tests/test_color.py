"""Cross-checked with frontend/src/lib/__tests__/stay-color.test.ts: every
vector in `VECTORS` below appears verbatim in that file too, hand-computed
once and pasted into both suites, so a change that breaks agreement between
the Python and TypeScript implementations fails on both sides independently
-- see apps/core/color.py's module docstring for why that agreement matters.
"""
from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.color import color_for_duration, default_stay_color_stops, validate_color_stops

STOPS = [
    {"seconds": 0, "color": "#22c55e"},
    {"seconds": 1800, "color": "#f59e0b"},
    {"seconds": 3600, "color": "#ef4444"},
]

# (seconds, expected_color) -- see this file's module docstring.
VECTORS = [
    (0, "#22c55e"),
    (900, "#8cb235"),  # halfway through the first segment
    (1800, "#f59e0b"),  # exactly on the middle stop
    (2700, "#f27128"),  # halfway through the second segment
    (3600, "#ef4444"),  # exactly on the last stop
    (7200, "#ef4444"),  # beyond the last stop: clamped, not extrapolated
    (-10, "#22c55e"),  # defensively clamped before the first stop too
]


@pytest.mark.parametrize("seconds, expected", VECTORS)
def test_color_for_duration_matches_the_shared_vectors(seconds, expected):
    assert color_for_duration(seconds, STOPS) == expected


def test_default_stops_start_green_and_end_red():
    stops = default_stay_color_stops()
    assert stops[0]["color"] == "#22c55e"
    assert stops[-1]["color"] == "#ef4444"


def test_default_stops_call_returns_a_fresh_list_each_time():
    """A Django JSONField default must be a callable returning a new object,
    never a shared mutable literal every unconfigured café would alias."""
    first = default_stay_color_stops()
    first[0]["color"] = "#000000"
    assert default_stay_color_stops()[0]["color"] == "#22c55e"


class TestValidateColorStops:
    def test_accepts_the_default_stops(self):
        validate_color_stops(default_stay_color_stops())  # must not raise

    def test_rejects_a_non_list(self):
        with pytest.raises(ValidationError):
            validate_color_stops({"seconds": 0, "color": "#22c55e"})

    def test_rejects_fewer_than_two_stops(self):
        with pytest.raises(ValidationError):
            validate_color_stops([{"seconds": 0, "color": "#22c55e"}])

    def test_rejects_a_first_stop_not_at_zero(self):
        with pytest.raises(ValidationError):
            validate_color_stops([{"seconds": 5, "color": "#22c55e"}, {"seconds": 10, "color": "#ef4444"}])

    def test_rejects_non_increasing_seconds(self):
        with pytest.raises(ValidationError):
            validate_color_stops(
                [{"seconds": 0, "color": "#22c55e"}, {"seconds": 0, "color": "#ef4444"}]
            )

    def test_rejects_decreasing_seconds(self):
        with pytest.raises(ValidationError):
            validate_color_stops(
                [
                    {"seconds": 0, "color": "#22c55e"},
                    {"seconds": 100, "color": "#f59e0b"},
                    {"seconds": 50, "color": "#ef4444"},
                ]
            )

    def test_rejects_a_negative_seconds_value(self):
        with pytest.raises(ValidationError):
            validate_color_stops(
                [{"seconds": 0, "color": "#22c55e"}, {"seconds": -10, "color": "#ef4444"}]
            )

    def test_rejects_a_non_integer_seconds_value(self):
        with pytest.raises(ValidationError):
            validate_color_stops(
                [{"seconds": 0, "color": "#22c55e"}, {"seconds": 30.5, "color": "#ef4444"}]
            )

    def test_rejects_a_boolean_seconds_value(self):
        """bool is a subclass of int in Python -- must be explicitly excluded,
        or `True`/`False` would silently pass as 1/0."""
        with pytest.raises(ValidationError):
            validate_color_stops(
                [{"seconds": 0, "color": "#22c55e"}, {"seconds": True, "color": "#ef4444"}]
            )

    def test_rejects_a_malformed_hex_color(self):
        with pytest.raises(ValidationError):
            validate_color_stops(
                [{"seconds": 0, "color": "green"}, {"seconds": 10, "color": "#ef4444"}]
            )

    def test_rejects_a_three_digit_hex_shorthand(self):
        with pytest.raises(ValidationError):
            validate_color_stops(
                [{"seconds": 0, "color": "#2c5"}, {"seconds": 10, "color": "#ef4444"}]
            )

    def test_rejects_a_stop_missing_a_required_key(self):
        with pytest.raises(ValidationError):
            validate_color_stops([{"seconds": 0}, {"seconds": 10, "color": "#ef4444"}])

    def test_rejects_a_stop_with_an_unexpected_extra_key(self):
        with pytest.raises(ValidationError):
            validate_color_stops(
                [
                    {"seconds": 0, "color": "#22c55e", "label": "fresh"},
                    {"seconds": 10, "color": "#ef4444"},
                ]
            )
