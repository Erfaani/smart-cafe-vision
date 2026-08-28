from __future__ import annotations

from rest_framework import serializers

from apps.tables.models import TableSession


class TableSessionSerializer(serializers.ModelSerializer):
    """Read-only: a session is entirely derived from the event pipeline (see
    apps/tables/projections.py), never created or edited through the API.

    `last_seen_at` is deliberately excluded, same reasoning as
    CustomerSessionSerializer -- internal housekeeping for
    apps.tables.tasks.close_stale_table_sessions, not meaningful for staff.
    """

    duration_seconds = serializers.FloatField(read_only=True)

    class Meta:
        model = TableSession
        fields = (
            "id", "camera_id", "table_zone_id", "table_name", "status",
            "occupied_at", "released_at", "release_reason",
            "duration_seconds", "created_at", "updated_at",
        )
        read_only_fields = fields


class TableUtilizationSerializer(serializers.Serializer):
    """Documents apps.tables.stats.table_utilization's shape for the schema."""

    table_zone_id = serializers.UUIDField()
    table_name = serializers.CharField()
    camera_id = serializers.UUIDField()
    occupied_seconds = serializers.FloatField()
    turnover_count = serializers.IntegerField()
    utilization_percent = serializers.FloatField()
