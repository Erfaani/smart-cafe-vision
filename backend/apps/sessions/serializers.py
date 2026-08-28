from __future__ import annotations

from rest_framework import serializers

from apps.sessions.models import CustomerSession


class CustomerSessionSerializer(serializers.ModelSerializer):
    """Read-only: a session is entirely derived from the event pipeline (see
    apps/sessions/projections.py), never created or edited through the API.

    `last_seen_at` is deliberately excluded -- it is internal housekeeping
    for apps.sessions.tasks.close_stale_sessions, not something meaningful
    for staff to look at (see the field's own docstring on the model).
    """

    duration_seconds = serializers.FloatField(read_only=True)
    # Phase 6: a snapshot-at-read-time colour, same caveat as
    # duration_seconds -- see both properties' docstrings on the model.
    color = serializers.CharField(read_only=True)

    class Meta:
        model = CustomerSession
        fields = (
            "id", "camera_id", "track_id", "status",
            "entry_at", "entry_zone_name",
            "exit_at", "exit_zone_name", "exit_reason",
            "duration_seconds", "color", "created_at", "updated_at",
        )
        read_only_fields = fields
