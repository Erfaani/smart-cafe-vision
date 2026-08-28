from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.cameras.views import CameraViewSet, CameraWorkerConfigView, TableZoneViewSet, ZoneViewSet

router = DefaultRouter()
router.register("", CameraViewSet, basename="camera")

# Hand-rolled nesting rather than a drf-nested-routers dependency: a zone (or
# a table) only ever exists under its camera (see ZoneViewSet's docstring).
zone_list = ZoneViewSet.as_view({"get": "list", "post": "create"})
zone_detail = ZoneViewSet.as_view(
    {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
)
table_list = TableZoneViewSet.as_view({"get": "list", "post": "create"})
table_detail = TableZoneViewSet.as_view(
    {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
)

urlpatterns = [
    path("worker-config/", CameraWorkerConfigView.as_view(), name="camera-worker-config"),
    path("<uuid:camera_id>/zones/", zone_list, name="zone-list"),
    path("<uuid:camera_id>/zones/<uuid:pk>/", zone_detail, name="zone-detail"),
    path("<uuid:camera_id>/tables/", table_list, name="table-list"),
    path("<uuid:camera_id>/tables/<uuid:pk>/", table_detail, name="table-detail"),
    path("", include(router.urls)),
]
