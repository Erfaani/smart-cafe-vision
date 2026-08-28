from __future__ import annotations

from rest_framework import serializers

from apps.display.models import DisplayMessage
from apps.tenants.models import Cafe


class DisplayMessageSerializer(serializers.ModelSerializer):
    """Staff CRUD shape. `cafe` writable, same reasoning as CameraSerializer:
    CafeScopedCreateMixin overrides it for a plain manager regardless of what
    is sent, but a superuser managing a café other than their own needs a way
    to name it explicitly."""

    cafe = serializers.PrimaryKeyRelatedField(queryset=Cafe.objects.all(), required=False)

    class Meta:
        model = DisplayMessage
        fields = ("id", "cafe", "text_en", "text_fa", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class PublicDisplayMessageSerializer(serializers.Serializer):
    """What the kiosk browser sees: the resolved text for its language only
    -- never text_en/text_fa both, so the display never has to duplicate the
    fallback-language logic DisplayMessage.text() already owns."""

    id = serializers.UUIDField()
    text = serializers.CharField()


class TrackedPersonSerializer(serializers.Serializer):
    """One synthetic dot -- position and colour only, no bounding box. See
    apps/display/live.py::get_public_live_tracks for why this is a box centre
    rather than the zone-crossing reference point."""

    track_id = serializers.IntegerField()
    x = serializers.FloatField()
    y = serializers.FloatField()
    entry_at = serializers.DateTimeField(allow_null=True)
    color = serializers.CharField()


class CameraLiveTracksSerializer(serializers.Serializer):
    camera_id = serializers.UUIDField()
    camera_name = serializers.CharField()
    resolution_width = serializers.IntegerField()
    resolution_height = serializers.IntegerField()
    people = TrackedPersonSerializer(many=True)


class PublicStatsSerializer(serializers.Serializer):
    occupancy = serializers.IntegerField()
    seating_capacity = serializers.IntegerField()
    visitors_today = serializers.IntegerField()
    average_stay_seconds = serializers.FloatField(allow_null=True)
    # Durations only, deliberately -- see get_public_stats's docstring for
    # why a track id or camera never appears here.
    leaderboard_seconds = serializers.ListField(child=serializers.FloatField())
