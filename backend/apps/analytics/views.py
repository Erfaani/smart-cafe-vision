from __future__ import annotations

import django_filters
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.analytics.models import DailyStat
from apps.analytics.serializers import DailyStatSerializer


class DailyStatFilterSet(django_filters.FilterSet):
    start = django_filters.DateFilter(field_name="date", lookup_expr="gte")
    end = django_filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = DailyStat
        fields = ("start", "end")


@extend_schema(tags=["analytics"])
class DailyStatViewSet(viewsets.ReadOnlyModelViewSet):
    """Daily rollups for a date range -- `?start=2026-08-01&end=2026-08-31`.

    Read-only, same principle as apps.sessions.views.CustomerSessionViewSet:
    this data is entirely derived, never created or edited directly. Open to
    any authenticated role, not just owner/manager -- it is insight, not
    configuration.

    Never paginated: a full year is at most ~366 rows, and a client asking
    for a range wants the whole thing to draw one chart, not eight pages of
    it.
    """

    serializer_class = DailyStatSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = DailyStatFilterSet
    pagination_class = None
    ordering = ["date"]
    queryset = DailyStat.objects.none()  # schema generation only; see get_queryset

    def get_queryset(self):
        user = self.request.user
        qs = DailyStat.objects.all()
        if user.is_superuser:
            return qs
        return qs.filter(cafe_id=user.cafe_id) if user.cafe_id else qs.none()
