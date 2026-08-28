from __future__ import annotations

from django.contrib import admin

from apps.sessions.models import CustomerSession


@admin.register(CustomerSession)
class CustomerSessionAdmin(admin.ModelAdmin):
    list_display = ("track_id", "camera_id", "cafe", "status", "entry_at", "exit_at", "exit_reason")
    list_filter = ("status", "exit_reason", "cafe")
    search_fields = ("track_id",)
    readonly_fields = ("last_seen_at",)
