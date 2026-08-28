"""Camera serializers.

Three, deliberately not one:

  * `CameraSerializer` -- what staff see. Never the password, never the
    decrypted URL.
  * `CameraTestConnectionSerializer` -- the probe result. A separate shape so
    a probe response can never be confused with a stored camera.
  * `CameraWorkerConfigSerializer` -- what the AI worker receives: the one
    place credentials leave the database, gated by `IsAIWorker`.

`ZoneSerializer` (staff CRUD) and `ZoneWorkerSerializer` (worker feed) are the
same split applied to a camera's entrance/exit lines: the former uses the
model's flat point_a_x/y columns directly, the latter reshapes them into
[x, y] pairs to match worker/zones.py::ZoneConfig and the parsing in
worker/manager.py::_parse_zone -- staff editing a zone and the worker
consuming one have different natural shapes for the same data.

`TableZoneSerializer` / `TableZoneWorkerSerializer` (Phase 9) follow the same
split, but the two shapes happen to coincide -- a rectangle's x1/y1/x2/y2 are
already what worker/manager.py::_parse_table expects, so the worker
serializer exists mainly to keep the "staff CRUD vs. worker feed" boundary
consistent rather than to reshape anything.
"""
from __future__ import annotations

from rest_framework import serializers

from apps.cameras.models import Camera, TableZone, Zone
from apps.tenants.models import Cafe


class CameraSerializer(serializers.ModelSerializer):
    # Write-only: accepted on create/update, never present in a response body.
    # Blank on update means "leave the existing password unchanged" -- an admin
    # editing the location of a camera should not have to retype its password.
    rtsp_password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, style={"input_type": "password"}
    )
    has_password = serializers.SerializerMethodField()
    is_stale = serializers.BooleanField(read_only=True)
    # Writable, not read-only: CafeScopedCreateMixin overrides it for a plain
    # manager regardless of what is sent, and defaults it for a superuser --
    # but a genuine platform admin managing a café other than their own needs
    # a way to name it explicitly, same as UserCreateSerializer.
    cafe = serializers.PrimaryKeyRelatedField(queryset=Cafe.objects.all(), required=False)

    class Meta:
        model = Camera
        fields = (
            "id", "cafe", "name", "location", "rtsp_url", "rtsp_username", "rtsp_password",
            "has_password", "transport", "is_enabled", "connection_status", "is_stale",
            "last_error", "last_connected_at", "last_frame_at", "last_fps",
            "resolution_width", "resolution_height", "last_person_count", "last_inference_ms",
            "last_track_count", "mount_type", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "connection_status", "last_error", "last_connected_at", "last_frame_at",
            "last_fps", "resolution_width", "resolution_height", "last_person_count",
            "last_inference_ms", "last_track_count", "created_at", "updated_at",
        )
        # `cafe` participates in the model's (cafe, name) unique constraint,
        # which would otherwise make DRF auto-generate a UniqueTogetherValidator
        # -- and that validator silently forces every field in the constraint
        # to become required, overriding `cafe`'s explicit required=False right
        # above. Uniqueness is still enforced: a violation hits the database
        # constraint and comes back as a 409 through the existing IntegrityError
        # handling in apps.core.exceptions, exactly as it did before `cafe`
        # became a serializer field at all.
        validators: list = []

    def get_has_password(self, obj: Camera) -> bool:
        return bool(obj.rtsp_password_encrypted)

    def create(self, validated_data: dict) -> Camera:
        password = validated_data.pop("rtsp_password", "")
        camera = Camera(**validated_data)
        if password:
            camera.set_password(password)
        camera.save()
        return camera

    def update(self, instance: Camera, validated_data: dict) -> Camera:
        password = validated_data.pop("rtsp_password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:  # empty string means "unchanged", checked above via `if`
            instance.set_password(password)
        instance.save()
        return instance


class ZoneSerializer(serializers.ModelSerializer):
    """CRUD shape for a camera's entrance/exit lines.

    `camera` is read-only here: a zone is always created through the nested
    `/cameras/{camera_id}/zones/` route, which sets it from the URL (and
    checks the camera's café against the requesting user) rather than trusting
    it in the request body -- see ZoneViewSet.perform_create.
    """

    class Meta:
        model = Zone
        fields = (
            "id", "camera", "name", "point_a_x", "point_a_y", "point_b_x", "point_b_y",
            "entry_is_positive_side", "is_active", "created_at", "updated_at",
        )
        read_only_fields = ("id", "camera", "created_at", "updated_at")


class ZoneWorkerSerializer(serializers.ModelSerializer):
    """One zone as the AI worker expects it -- point pairs, not flat columns.

    Must agree with worker/manager.py::_parse_zone's key names exactly; that
    function is the only consumer of this shape.
    """

    point_a = serializers.SerializerMethodField()
    point_b = serializers.SerializerMethodField()

    class Meta:
        model = Zone
        fields = ("id", "name", "point_a", "point_b", "entry_is_positive_side")

    def get_point_a(self, obj: Zone) -> list[float]:
        return [obj.point_a_x, obj.point_a_y]

    def get_point_b(self, obj: Zone) -> list[float]:
        return [obj.point_b_x, obj.point_b_y]


class TableZoneSerializer(serializers.ModelSerializer):
    """CRUD shape for a camera's tables. `camera` is read-only, same reasoning
    as ZoneSerializer -- set from the URL by the nested viewset, never
    trusted from the request body."""

    class Meta:
        model = TableZone
        fields = ("id", "camera", "name", "x1", "y1", "x2", "y2", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "camera", "created_at", "updated_at")


class TableZoneWorkerSerializer(serializers.ModelSerializer):
    """One table as the AI worker expects it -- see
    worker/manager.py::_parse_table, the only consumer of this shape."""

    class Meta:
        model = TableZone
        fields = ("id", "name", "x1", "y1", "x2", "y2")


class CameraTestConnectionSerializer(serializers.Serializer):
    """Documents the response of the test-connection action for the schema."""

    status = serializers.CharField()
    ok = serializers.BooleanField()
    message = serializers.CharField()
    detail = serializers.CharField(required=False, allow_blank=True)


class DetectionBoxSerializer(serializers.Serializer):
    """A single anonymous bounding box -- pixel coordinates and confidence
    only. No identity of any kind travels through this shape."""

    x1 = serializers.FloatField()
    y1 = serializers.FloatField()
    x2 = serializers.FloatField()
    y2 = serializers.FloatField()
    confidence = serializers.FloatField()


class CameraDetectionsSerializer(serializers.Serializer):
    """Documents the near-real-time detection summary for the schema."""

    person_count = serializers.IntegerField()
    inference_ms = serializers.FloatField()
    boxes = DetectionBoxSerializer(many=True)
    updated_at = serializers.DateTimeField()


class TrackedBoxSerializer(serializers.Serializer):
    """A single anonymous tracked box -- pixel coordinates, confidence, and a
    temporary track id that is meaningless outside this camera's current
    session. No identity of any kind travels through this shape."""

    track_id = serializers.IntegerField()
    x1 = serializers.FloatField()
    y1 = serializers.FloatField()
    x2 = serializers.FloatField()
    y2 = serializers.FloatField()
    confidence = serializers.FloatField()


class CameraTracksSerializer(serializers.Serializer):
    """Documents the near-real-time tracking summary for the schema."""

    track_count = serializers.IntegerField()
    tracks = TrackedBoxSerializer(many=True)
    updated_at = serializers.DateTimeField()


class CameraWorkerConfigSerializer(serializers.ModelSerializer):
    """What the AI worker needs to open a stream. Only ever served to a
    request authenticated with the worker's service token."""

    url = serializers.SerializerMethodField()
    zones = serializers.SerializerMethodField()
    tables = serializers.SerializerMethodField()

    class Meta:
        model = Camera
        fields = ("id", "name", "url", "transport", "zones", "tables")

    def get_url(self, obj: Camera) -> str:
        return obj.build_connection_url()

    def get_zones(self, obj: Camera) -> list[dict]:
        # Disabled lines are excluded rather than sent with a flag, so the
        # worker (worker/manager.py::_parse_zone) never needs to know
        # is_active exists -- a disabled zone simply is not there.
        # CameraWorkerConfigView prefetches this filtered set as
        # `active_zones` to avoid one query per camera; fall back to a live
        # filter for any other caller of this serializer.
        active_zones = getattr(obj, "active_zones", None)
        if active_zones is None:
            active_zones = obj.zones.filter(is_active=True)
        return ZoneWorkerSerializer(active_zones, many=True).data

    def get_tables(self, obj: Camera) -> list[dict]:
        # Same is_active-excluded, prefetch-or-fall-back pattern as
        # get_zones above.
        active_tables = getattr(obj, "active_tables", None)
        if active_tables is None:
            active_tables = obj.tables.filter(is_active=True)
        return TableZoneWorkerSerializer(active_tables, many=True).data
