from __future__ import annotations

from django.contrib import admin

from apps.events.models import TrackingEvent


@admin.register(TrackingEvent)
class TrackingEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "occurred_at", "camera_id", "worker_id", "cafe")
    list_filter = ("event_type", "cafe")
    search_fields = ("event_id", "worker_id")
    date_hierarchy = "occurred_at"
    readonly_fields = tuple(f.name for f in TrackingEvent._meta.fields)

    def has_add_permission(self, request) -> bool:
        # The event log is append-only from the bus; hand-written rows would
        # corrupt the analytics that are derived from it.
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
