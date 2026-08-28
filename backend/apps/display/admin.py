from __future__ import annotations

from django.contrib import admin

from apps.display.models import DisplayMessage


@admin.register(DisplayMessage)
class DisplayMessageAdmin(admin.ModelAdmin):
    list_display = ("text_en", "cafe", "is_active")
    list_filter = ("is_active", "cafe")
    search_fields = ("text_en", "text_fa")
