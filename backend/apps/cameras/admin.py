from __future__ import annotations

from django.contrib import admin

from apps.cameras.models import Camera, TableZone, Zone


@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = (
        "name", "cafe", "location", "connection_status", "is_enabled", "mount_type", "last_frame_at",
    )
    list_filter = ("connection_status", "is_enabled", "mount_type", "cafe")
    search_fields = ("name", "location", "rtsp_url")
    readonly_fields = (
        "connection_status", "last_error", "last_connected_at", "last_frame_at",
        "last_fps", "resolution_width", "resolution_height",
    )
    # The encrypted column is never shown, even to a superuser in the admin --
    # there is no legitimate reason to view ciphertext, and it invites someone
    # to "helpfully" copy it into a form field somewhere.
    exclude = ("rtsp_password_encrypted",)


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "camera", "entry_is_positive_side", "is_active")
    list_filter = ("is_active", "camera__cafe")
    search_fields = ("name", "camera__name")


@admin.register(TableZone)
class TableZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "camera", "is_active")
    list_filter = ("is_active", "camera__cafe")
    search_fields = ("name", "camera__name")
