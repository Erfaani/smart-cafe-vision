from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.analytics.views import DailyStatViewSet

router = DefaultRouter()
router.register("daily", DailyStatViewSet, basename="daily-stat")

urlpatterns = [
    path("", include(router.urls)),
]
