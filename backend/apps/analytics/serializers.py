from __future__ import annotations

from rest_framework import serializers

from apps.analytics.models import DailyStat


class DailyStatSerializer(serializers.ModelSerializer):
    """Read-only: a rollup over the event log, never created or edited
    through the API -- see apps/analytics/rollups.py.

    `total_stay_seconds` and `ended_session_count` travel alongside the
    already-averaged `average_stay_seconds` so a client aggregating several
    days can compute a correctly-weighted average (sum of totals / sum of
    counts) instead of naively averaging each day's average, which silently
    misweights a slow Tuesday the same as a busy Saturday.
    """

    class Meta:
        model = DailyStat
        fields = (
            "date", "visitor_count", "ended_session_count", "total_stay_seconds",
            "average_stay_seconds", "longest_stay_seconds", "hourly_entries",
            "peak_occupancy", "peak_occupancy_at", "is_final",
        )
        read_only_fields = fields
