from __future__ import annotations

from django.utils.dateparse import parse_datetime
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tables.models import TableSession
from apps.tables.serializers import TableSessionSerializer, TableUtilizationSerializer
from apps.tables.stats import table_utilization
from apps.tenants.models import Cafe


@extend_schema(tags=["tables"])
class TableSessionViewSet(viewsets.ReadOnlyModelViewSet):
    """Current and historical table sessions -- read-only, same principle as
    apps.sessions.views.CustomerSessionViewSet."""

    serializer_class = TableSessionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "camera_id", "table_zone_id"]
    ordering = ["-occupied_at"]
    queryset = TableSession.objects.none()  # schema generation only; see get_queryset

    def get_queryset(self):
        user = self.request.user
        qs = TableSession.objects.all()
        if user.is_superuser:
            return qs
        return qs.filter(cafe_id=user.cafe_id) if user.cafe_id else qs.none()


@extend_schema(tags=["tables"], responses={200: TableUtilizationSerializer(many=True)})
class TableUtilizationView(APIView):
    """`?start=<iso datetime>&end=<iso datetime>` -- occupied time and
    turnover count per table over that range. See apps/tables/stats.py."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        user = request.user
        cafe_id = user.cafe_id
        if not user.is_superuser and not cafe_id:
            return Response([])

        start = self._parse(request.query_params.get("start"))
        end = self._parse(request.query_params.get("end"))
        if start is None or end is None:
            return Response(
                {
                    "error": {
                        "code": "invalid_range",
                        "message": "Both start and end are required, as ISO-8601 datetimes.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user.is_superuser:
            explicit_cafe_id = request.query_params.get("cafe_id", cafe_id)
            cafe = Cafe.objects.filter(pk=explicit_cafe_id).first() if explicit_cafe_id else None
        else:
            cafe = Cafe.objects.filter(pk=cafe_id).first()

        if cafe is None:
            return Response([])

        return Response(table_utilization(cafe, start, end))

    @staticmethod
    def _parse(value: str | None):
        if not value:
            return None
        return parse_datetime(value)
