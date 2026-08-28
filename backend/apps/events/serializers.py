from __future__ import annotations

from rest_framework import serializers

from apps.events.models import TrackingEvent


class TrackingEventSerializer(serializers.ModelSerializer):
    ingest_lag_seconds = serializers.FloatField(read_only=True)

    class Meta:
        model = TrackingEvent
        fields = (
            "id",
            "event_id",
            "event_type",
            "occurred_at",
            "ingested_at",
            "ingest_lag_seconds",
            "camera_id",
            "worker_id",
            "payload",
        )
        read_only_fields = fields


class EventIngestSerializer(serializers.Serializer):
    """The wire shape of one event, mirroring scv_contracts.Event.

    Used for documentation and light validation only: `Event.from_dict` remains
    the single authority, so the schema can never diverge from what is actually
    accepted.
    """

    schema_version = serializers.IntegerField(default=1)
    event_id = serializers.UUIDField()
    type = serializers.CharField()
    cafe_id = serializers.UUIDField()
    camera_id = serializers.UUIDField(required=False, allow_null=True)
    worker_id = serializers.CharField(required=False, allow_blank=True)
    occurred_at = serializers.DateTimeField()
    payload = serializers.JSONField(required=False)


class EventIngestResultSerializer(serializers.Serializer):
    accepted = serializers.IntegerField()
    stored = serializers.IntegerField()
    duplicate = serializers.IntegerField()
    rejected = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.DictField(), required=False)


class EventBusStatsSerializer(serializers.Serializer):
    stream = serializers.CharField()
    group = serializers.CharField()
    length = serializers.IntegerField(help_text="Entries currently held in the stream.")
    pending = serializers.IntegerField(help_text="Delivered but not yet acknowledged.")
