from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.tables.views import TableSessionViewSet, TableUtilizationView

router = DefaultRouter()
router.register("sessions", TableSessionViewSet, basename="table-session")

urlpatterns = [
    path("utilization/", TableUtilizationView.as_view(), name="table-utilization"),
    path("", include(router.urls)),
]
