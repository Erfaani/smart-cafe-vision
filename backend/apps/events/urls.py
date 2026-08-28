from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.events.views import EventBusStatsView, EventIngestView, TrackingEventViewSet

router = DefaultRouter()
router.register("", TrackingEventViewSet, basename="tracking-event")

urlpatterns = [
    path("ingest/", EventIngestView.as_view(), name="event-ingest"),
    path("bus-stats/", EventBusStatsView.as_view(), name="event-bus-stats"),
    path("", include(router.urls)),
]
