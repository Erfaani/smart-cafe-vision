from __future__ import annotations

from django.contrib import admin

from apps.tables.models import TableSession


@admin.register(TableSession)
class TableSessionAdmin(admin.ModelAdmin):
    list_display = ("table_name", "camera_id", "cafe", "status", "occupied_at", "released_at", "release_reason")
    list_filter = ("status", "release_reason", "cafe")
    search_fields = ("table_name",)
    readonly_fields = ("last_seen_at",)
