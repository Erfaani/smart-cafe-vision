from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.sessions.models import CustomerSession
from apps.sessions.serializers import CustomerSessionSerializer


@extend_schema(tags=["sessions"])
class CustomerSessionViewSet(viewsets.ReadOnlyModelViewSet):
    """Current and historical customer sessions -- read-only, same principle
    as apps.events.views.TrackingEventViewSet: this data is a projection over
    the event log, not something staff create or edit directly."""

    serializer_class = CustomerSessionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "camera_id"]
    ordering = ["-entry_at"]
    queryset = CustomerSession.objects.none()  # schema generation only; see get_queryset

    def get_queryset(self):
        user = self.request.user
        # select_related("cafe"): the serializer's `color` field reads
        # cafe.stay_color_stops for every row -- without this, that is one
        # extra query per session instead of one join for the whole page.
        qs = CustomerSession.objects.select_related("cafe")
        if user.is_superuser:
            return qs
        return qs.filter(cafe_id=user.cafe_id) if user.cafe_id else qs.none()
