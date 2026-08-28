from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.display.views import DisplayMessageViewSet

router = DefaultRouter()
router.register("", DisplayMessageViewSet, basename="display-message")

urlpatterns = [
    path("", include(router.urls)),
]
