"""Operational endpoints."""
from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import health


class HealthView(APIView):
    """Liveness: is this process able to answer at all?

    Intentionally does no I/O, so a container orchestrator never restarts the
    backend just because PostgreSQL is briefly busy.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        tags=["system"],
        responses={200: dict},
        examples=[OpenApiExample("alive", value={"status": "ok"})],
    )
    def get(self, request: Request) -> Response:
        return Response({"status": health.OK})


class ReadinessView(APIView):
    """Readiness: are the dependencies this install needs actually reachable?

    Returns 503 when a critical component is down so a load balancer or the
    café's own monitoring can act on it, while still returning the full body so
    a technician can see which component failed.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(tags=["system"], responses={200: dict, 503: dict})
    def get(self, request: Request) -> Response:
        report = health.collect()
        http_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if report["status"] == health.DOWN
            else status.HTTP_200_OK
        )
        return Response(report, status=http_status)
