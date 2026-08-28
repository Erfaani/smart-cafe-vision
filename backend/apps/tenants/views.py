from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsOwnerOrManager
from apps.tenants.models import Cafe
from apps.tenants.serializers import CafeSerializer, PublicCafeSerializer


@extend_schema(tags=["cafes"])
class CafeViewSet(viewsets.ModelViewSet):
    serializer_class = CafeSerializer
    permission_classes = [IsOwnerOrManager]
    lookup_field = "slug"
    # Declared for schema generation only; get_queryset() below is what runs.
    queryset = Cafe.objects.none()

    def get_queryset(self):
        user = self.request.user
        qs = Cafe.objects.all()
        # Staff of one café never see another tenant's row, even though v1
        # installs a single café per server.
        if user.is_superuser:
            return qs
        return qs.filter(pk=user.cafe_id) if user.cafe_id else qs.none()


@extend_schema(tags=["public-display"], responses={200: PublicCafeSerializer})
class PublicCafeView(APIView):
    """Branding and privacy text for the public display page.

    Unauthenticated on purpose: the TV in the corner of the café runs a kiosk
    browser with no credentials. It receives only non-sensitive branding.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request, slug: str) -> Response:
        cafe = get_object_or_404(Cafe, slug=slug, is_active=True)
        serializer = PublicCafeSerializer(
            cafe, context={"request": request, "language": request.query_params.get("lang")}
        )
        return Response(serializer.data)
