from __future__ import annotations

import zoneinfo

from rest_framework import serializers

from apps.tenants.models import Cafe


class CafeSerializer(serializers.ModelSerializer):
    privacy_notice = serializers.SerializerMethodField()

    class Meta:
        model = Cafe
        fields = (
            "id",
            "name",
            "slug",
            "logo",
            "timezone",
            "default_language",
            "seating_capacity",
            "is_active",
            "stay_color_stops",
            "privacy_notice_en",
            "privacy_notice_fa",
            "privacy_notice",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def get_privacy_notice(self, obj: Cafe) -> str:
        return obj.privacy_notice()

    def validate_timezone(self, value: str) -> str:
        # A bad timezone silently shifts every analytics bucket, so reject it at
        # the edge rather than discovering it in a report.
        try:
            zoneinfo.ZoneInfo(value)
        except Exception as exc:
            raise serializers.ValidationError(
                f"{value!r} is not a valid IANA time zone."
            ) from exc
        return value


class PublicCafeSerializer(serializers.ModelSerializer):
    """Everything the public display is allowed to know about a café.

    Explicitly a separate serializer, not a field subset of the admin one: it
    must be impossible to widen the public payload by editing the admin model.
    `stay_color_stops` belongs here deliberately (Phase 6): it is a colour
    palette, not café data, and Phase 7's display needs it unauthenticated to
    colour a customer's box the same way the dashboard colours their row --
    see apps/core/color.py. `seating_capacity` (Phase 7) is the denominator
    the display's statistics mode needs for an occupancy percentage -- a
    venue's stated seating capacity is not sensitive the way individual
    tracking data is, and is routinely public information anyway (menus,
    booking pages, review sites).
    """

    privacy_notice = serializers.SerializerMethodField()

    class Meta:
        model = Cafe
        fields = (
            "name", "slug", "logo", "default_language", "privacy_notice",
            "stay_color_stops", "seating_capacity",
        )

    def get_privacy_notice(self, obj: Cafe) -> str:
        return obj.privacy_notice(self.context.get("language"))
