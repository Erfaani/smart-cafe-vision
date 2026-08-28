from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.sessions.views import CustomerSessionViewSet

router = DefaultRouter()
router.register("", CustomerSessionViewSet, basename="customer-session")

urlpatterns = [
    path("", include(router.urls)),
]
