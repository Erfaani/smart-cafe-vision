from __future__ import annotations

from django.contrib import admin

from apps.analytics.models import DailyStat


@admin.register(DailyStat)
class DailyStatAdmin(admin.ModelAdmin):
    list_display = ("date", "cafe", "visitor_count", "average_stay_seconds", "peak_occupancy", "is_final")
    list_filter = ("is_final", "cafe")
    search_fields = ("cafe__name",)
    date_hierarchy = "date"
