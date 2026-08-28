from __future__ import annotations

import logging

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAIWorker
from apps.events.ingest import ingest_many
from apps.events.models import TrackingEvent
from apps.events.serializers import (
    EventBusStatsSerializer,
    EventIngestResultSerializer,
    EventIngestSerializer,
    TrackingEventSerializer,
)
from scv_contracts import ContractError, Event

logger = logging.getLogger("smartcafe.events")

# One HTTP request may not carry an unbounded batch: a runaway worker should get
# a 400, not exhaust the backend's memory.
MAX_BATCH_SIZE = 500


@extend_schema(
    tags=["events"],
    request=EventIngestSerializer(many=True),
    responses={202: EventIngestResultSerializer, 400: EventIngestResultSerializer},
)
class EventIngestView(APIView):
    """HTTP ingest for AI worker events.

    The Redis stream is the primary path. This endpoint exists for two real
    situations: a worker running on a separate machine that can reach the API
    but not Redis, and manual replay during support work. Both paths converge on
    the same `ingest()` function, so behaviour cannot drift between them.
    """

    permission_classes = [IsAIWorker]
    authentication_classes: list = []

    def post(self, request: Request) -> Response:
        raw = request.data
        items = raw if isinstance(raw, list) else [raw]
        if len(items) > MAX_BATCH_SIZE:
            return Response(
                {
                    "error": {
                        "code": "batch_too_large",
                        "message": f"At most {MAX_BATCH_SIZE} events per request.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        events: list[Event] = []
        errors: list[dict[str, str]] = []
        for index, item in enumerate(items):
            try:
                events.append(Event.from_dict(item))
            except (ContractError, AttributeError, TypeError) as exc:
                errors.append({"index": str(index), "message": str(exc)})

        tally = ingest_many(events)
        body = {"accepted": tally["stored"], **tally}
        if errors:
            body["errors"] = errors
        http_status = status.HTTP_400_BAD_REQUEST if errors and not events else status.HTTP_202_ACCEPTED
        return Response(body, status=http_status)


@extend_schema(tags=["events"])
class TrackingEventViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only event log for the dashboard and for support diagnosis."""

    serializer_class = TrackingEventSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["event_type", "camera_id", "worker_id"]
    ordering = ["-occurred_at"]
    # Declared for schema generation only; get_queryset() below is what runs.
    queryset = TrackingEvent.objects.none()

    def get_queryset(self):
        user = self.request.user
        qs = TrackingEvent.objects.all()
        if user.is_superuser:
            return qs
        return qs.filter(cafe_id=user.cafe_id) if user.cafe_id else qs.none()


@extend_schema(tags=["events"], responses={200: EventBusStatsSerializer, 503: None})
class EventBusStatsView(APIView):
    """Stream depth and unacknowledged count — the ingest health signal."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        from apps.events.bus import EventBus

        try:
            return Response(EventBus().stats())
        except Exception as exc:
            logger.warning("event_bus_stats_failed error=%s", type(exc).__name__)
            return Response(
                {"error": {"code": "event_bus_unavailable", "message": "Redis is unreachable."}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
