from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsOwnerOrManager
from apps.core.viewsets import CafeScopedCreateMixin
from apps.display.live import get_public_live_tracks, get_public_stats
from apps.display.models import DisplayMessage
from apps.display.serializers import (
    CameraLiveTracksSerializer,
    DisplayMessageSerializer,
    PublicDisplayMessageSerializer,
    PublicStatsSerializer,
)
from apps.tenants.models import Cafe


@extend_schema(tags=["display"])
class DisplayMessageViewSet(CafeScopedCreateMixin, viewsets.ModelViewSet):
    """Staff CRUD for the entertainment-mode message rotation."""

    serializer_class = DisplayMessageSerializer
    permission_classes = [IsOwnerOrManager]
    queryset = DisplayMessage.objects.none()  # schema generation only; see get_queryset

    def get_queryset(self):
        user = self.request.user
        qs = DisplayMessage.objects.all()
        if user.is_superuser:
            return qs
        return qs.filter(cafe_id=user.cafe_id) if user.cafe_id else qs.none()


def _get_active_cafe(slug: str) -> Cafe:
    return get_object_or_404(Cafe, slug=slug, is_active=True)


@extend_schema(tags=["public-display"], responses={200: CameraLiveTracksSerializer(many=True)})
class PublicDisplayLiveView(APIView):
    """Live tracked-person positions for every enabled, connected camera --
    the public, unauthenticated counterpart to
    apps.cameras.views.CameraViewSet.tracks, aggregated across a whole café
    rather than one camera at a time. See apps/display/live.py."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request, slug: str) -> Response:
        cafe = _get_active_cafe(slug)
        return Response(get_public_live_tracks(cafe))


@extend_schema(tags=["public-display"], responses={200: PublicStatsSerializer})
class PublicDisplayStatsView(APIView):
    """Occupancy and an anonymous, duration-only leaderboard. See
    apps/display/live.py::get_public_stats."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request, slug: str) -> Response:
        cafe = _get_active_cafe(slug)
        return Response(get_public_stats(cafe))


@extend_schema(tags=["public-display"], responses={200: PublicDisplayMessageSerializer(many=True)})
class PublicDisplayMessagesView(APIView):
    """Active entertainment-mode messages, pre-resolved to one language."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request, slug: str) -> Response:
        cafe = _get_active_cafe(slug)
        language = request.query_params.get("lang") or cafe.default_language
        messages = DisplayMessage.objects.filter(cafe=cafe, is_active=True)
        body = [{"id": message.id, "text": message.text(language)} for message in messages]
        return Response(body)
