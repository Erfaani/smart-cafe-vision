from __future__ import annotations

from django.contrib import admin

from apps.tenants.models import Cafe


@admin.register(Cafe)
class CafeAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "timezone", "seating_capacity", "is_active")
    list_filter = ("is_active", "default_language")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    # JSONField renders as a plain textarea by default -- fine here, since a
    # café owner configures stay_color_stops through the dashboard settings
    # page, not the admin; this is a technician's escape hatch.
    fields = (
        "name", "slug", "logo", "timezone", "default_language", "seating_capacity",
        "is_active", "stay_color_stops", "privacy_notice_en", "privacy_notice_fa",
    )
