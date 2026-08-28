from __future__ import annotations

import logging

from django.db.models import Prefetch
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cameras.detections import get_latest_detections, get_latest_tracks
from apps.cameras.models import Camera, TableZone, Zone
from apps.cameras.rtsp_probe import probe_rtsp
from apps.cameras.serializers import (
    CameraDetectionsSerializer,
    CameraSerializer,
    CameraTestConnectionSerializer,
    CameraTracksSerializer,
    CameraWorkerConfigSerializer,
    TableZoneSerializer,
    ZoneSerializer,
)
from apps.cameras.streaming import get_latest_frame, mjpeg_frames
from apps.core.permissions import IsAIWorker, IsOwnerOrManager
from apps.core.viewsets import CafeScopedCreateMixin

logger = logging.getLogger("smartcafe.cameras")


@extend_schema(tags=["cameras"])
class CameraViewSet(CafeScopedCreateMixin, viewsets.ModelViewSet):
    serializer_class = CameraSerializer
    permission_classes = [IsOwnerOrManager]
    queryset = Camera.objects.none()  # schema generation only; see get_queryset

    def get_queryset(self):
        user = self.request.user
        qs = Camera.objects.all()
        if user.is_superuser:
            return qs
        return qs.filter(cafe_id=user.cafe_id) if user.cafe_id else qs.none()

    @extend_schema(request=None, responses={200: CameraTestConnectionSerializer})
    @action(detail=True, methods=["post"], url_path="test-connection")
    def test_connection(self, request: Request, pk: str | None = None) -> Response:
        """Run the RTSP handshake synchronously and report the result.

        Uses whatever credentials are currently saved on the camera -- not
        anything in the request body -- so this always tests what the worker
        will actually connect with.
        """
        camera = self.get_object()
        result = probe_rtsp(camera.rtsp_url, camera.rtsp_username, camera.get_password())

        logger.info(
            "camera_test_connection camera=%s status=%s", camera.id, result.status
        )
        body = {
            "status": str(result.status),
            "ok": result.ok,
            "message": result.message,
            "detail": result.detail,
        }
        return Response(body, status=status.HTTP_200_OK if result.ok else status.HTTP_502_BAD_GATEWAY)

    @extend_schema(responses={200: {"content": {"image/jpeg": {}}}, 404: None})
    @action(detail=True, methods=["get"], url_path="snapshot.jpg")
    def snapshot(self, request: Request, pk: str | None = None) -> HttpResponse:
        camera = self.get_object()
        frame = get_latest_frame(str(camera.id))
        if frame is None:
            raise Http404("No frame has been captured for this camera yet.")
        return HttpResponse(frame, content_type="image/jpeg")

    @extend_schema(responses={200: CameraDetectionsSerializer, 404: None})
    @action(detail=True, methods=["get"], url_path="detections")
    def detections(self, request: Request, pk: str | None = None) -> Response:
        """Near-real-time detection summary, not the periodic persisted
        snapshot on the camera row -- see apps/cameras/detections.py."""
        camera = self.get_object()
        summary = get_latest_detections(str(camera.id))
        if summary is None:
            raise Http404("No detection has been recorded for this camera yet.")
        return Response(summary)

    @extend_schema(responses={200: CameraTracksSerializer, 404: None})
    @action(detail=True, methods=["get"], url_path="tracks")
    def tracks(self, request: Request, pk: str | None = None) -> Response:
        """Near-real-time tracking summary, anonymous track ids included --
        see apps/cameras/detections.py:get_latest_tracks."""
        camera = self.get_object()
        summary = get_latest_tracks(str(camera.id))
        if summary is None:
            raise Http404("No tracking has been recorded for this camera yet.")
        return Response(summary)

    @extend_schema(responses={200: {"content": {"multipart/x-mixed-replace": {}}}})
    @action(detail=True, methods=["get"], url_path="stream.mjpg")
    def stream(self, request: Request, pk: str | None = None) -> StreamingHttpResponse:
        camera = self.get_object()
        from apps.cameras.streaming import MJPEG_BOUNDARY

        response = StreamingHttpResponse(
            mjpeg_frames(str(camera.id)),
            content_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        )
        # Every intermediary (nginx, the browser) must treat this as live.
        response["Cache-Control"] = "no-cache, no-store"
        response["X-Accel-Buffering"] = "no"
        return response


@extend_schema(tags=["cameras"])
class ZoneViewSet(viewsets.ModelViewSet):
    """CRUD for one camera's entrance/exit lines.

    Nested under /cameras/{camera_id}/zones/ rather than given a top-level
    route: a zone has no meaning or identity outside its camera, so there is
    no "list every zone across every camera" use case to serve.
    """

    serializer_class = ZoneSerializer
    permission_classes = [IsOwnerOrManager]
    # A camera has at most a handful of entrance/exit lines -- pagination
    # would only force the zone editor to page through an envelope for what
    # is always a short, complete list.
    pagination_class = None
    queryset = Zone.objects.none()  # schema generation only; see get_queryset

    def get_camera(self) -> Camera:
        user = self.request.user
        qs = Camera.objects.all() if user.is_superuser else Camera.objects.filter(cafe_id=user.cafe_id)
        return get_object_or_404(qs, pk=self.kwargs["camera_id"])

    def get_queryset(self):
        return Zone.objects.filter(camera=self.get_camera())

    def perform_create(self, serializer) -> None:
        serializer.save(camera=self.get_camera())


@extend_schema(tags=["cameras"])
class TableZoneViewSet(viewsets.ModelViewSet):
    """CRUD for one camera's tables.

    Nested under /cameras/{camera_id}/tables/, same reasoning as
    ZoneViewSet: a table has no meaning outside its camera.
    """

    serializer_class = TableZoneSerializer
    permission_classes = [IsOwnerOrManager]
    # Same reasoning as ZoneViewSet: a café has at most a handful of tables.
    pagination_class = None
    queryset = TableZone.objects.none()  # schema generation only; see get_queryset

    def get_camera(self) -> Camera:
        user = self.request.user
        qs = Camera.objects.all() if user.is_superuser else Camera.objects.filter(cafe_id=user.cafe_id)
        return get_object_or_404(qs, pk=self.kwargs["camera_id"])

    def get_queryset(self):
        return TableZone.objects.filter(camera=self.get_camera())

    def perform_create(self, serializer) -> None:
        serializer.save(camera=self.get_camera())


@extend_schema(tags=["cameras"])
class CameraWorkerConfigView(APIView):
    """The camera list an AI worker uses to know what to capture, credentials
    included. The one endpoint in the system that returns a decrypted RTSP
    password, and it does so only to a request bearing the worker's service
    token (spec §17: the worker is a separate trust domain from the dashboard).
    """

    permission_classes = [IsAIWorker]
    authentication_classes: list = []

    @extend_schema(
        parameters=[],
        responses={200: CameraWorkerConfigSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        cafe_id = request.query_params.get("cafe_id", "")
        if not cafe_id:
            return Response(
                {"error": {"code": "cafe_id_required", "message": "cafe_id is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cameras = Camera.objects.filter(cafe_id=cafe_id, is_enabled=True).prefetch_related(
            Prefetch("zones", queryset=Zone.objects.filter(is_active=True), to_attr="active_zones"),
            Prefetch("tables", queryset=TableZone.objects.filter(is_active=True), to_attr="active_tables"),
        )
        return Response(CameraWorkerConfigSerializer(cameras, many=True).data)
