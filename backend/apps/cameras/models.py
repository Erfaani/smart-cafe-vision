"""Camera model.

Fields split deliberately into three groups:

  * what an admin configures (name, location, connection details)
  * what is observed from the actual stream (resolution, fps, status)
  * nothing else

Resolution and FPS are never admin-entered. Spec §22 is explicit that camera FPS
must not be assumed to equal AI FPS, and an editable "expected resolution" field
would just be a number that drifts from reality the moment someone swaps a
camera. Reporting what the stream actually delivers is more useful to whoever
is diagnosing a bad connection, and it can only be filled in once the AI worker
has actually opened the stream (Phase 2) -- so these fields start null.
"""
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.cameras.validators import validate_rtsp_url
from apps.core.crypto import decrypt_secret, encrypt_secret
from apps.core.models import BaseModel, CafeScopedModel


class Camera(CafeScopedModel):
    class ConnectionStatus(models.TextChoices):
        UNKNOWN = "unknown", _("Unknown")
        CONNECTING = "connecting", _("Connecting")
        CONNECTED = "connected", _("Connected")
        DISCONNECTED = "disconnected", _("Disconnected")
        ERROR = "error", _("Error")

    class Transport(models.TextChoices):
        TCP = "tcp", _("TCP")
        UDP = "udp", _("UDP")

    class MountType(models.TextChoices):
        UNKNOWN = "unknown", _("Unknown")
        OVERHEAD = "overhead", _("Overhead")
        WALL = "wall", _("Wall-mounted")

    name = models.CharField(max_length=120)
    location = models.CharField(
        max_length=120, blank=True, default="", help_text=_("e.g. Entrance, Main hall")
    )

    rtsp_url = models.CharField(
        max_length=500,
        validators=[validate_rtsp_url],
        help_text=_("rtsp://host:port/path — no username or password in the URL."),
    )
    rtsp_username = models.CharField(max_length=128, blank=True, default="")
    rtsp_password_encrypted = models.CharField(max_length=512, blank=True, default="")
    transport = models.CharField(max_length=8, choices=Transport.choices, default=Transport.TCP)

    is_enabled = models.BooleanField(default=True)

    connection_status = models.CharField(
        max_length=16, choices=ConnectionStatus.choices, default=ConnectionStatus.UNKNOWN
    )
    # Truncated: this is a human-readable diagnostic, not a place to accumulate
    # an unbounded traceback from a misbehaving camera.
    last_error = models.CharField(max_length=255, blank=True, default="")
    last_connected_at = models.DateTimeField(null=True, blank=True)
    last_frame_at = models.DateTimeField(null=True, blank=True)
    last_fps = models.FloatField(null=True, blank=True)
    resolution_width = models.PositiveIntegerField(null=True, blank=True)
    resolution_height = models.PositiveIntegerField(null=True, blank=True)

    # Phase 3: a periodic snapshot from the worker's last detection tick, not
    # a live figure -- see apps/cameras/detections.py for the near-real-time
    # value read straight from Redis. This one is what analytics can query
    # historically once TrackingEvent rows exist to derive it from.
    last_person_count = models.PositiveIntegerField(null=True, blank=True)
    last_inference_ms = models.FloatField(null=True, blank=True)

    # Phase 4: the tracker's considered view, as of the same periodic snapshot
    # -- deliberately a separate column from last_person_count, not a
    # duplicate. They can genuinely differ: last_person_count is one instant's
    # raw detector output, while this keeps a briefly-occluded person counted
    # through the gap instead of flickering to zero and back.
    last_track_count = models.PositiveIntegerField(null=True, blank=True)

    # Phase 9: table occupancy is only as reliable as the camera's angle on
    # the tables it covers. Admin-entered, not observed -- there is nothing
    # in a frame that tells the worker whether it is looking straight down
    # or across a room. Defaults to "unknown" rather than assuming overhead,
    # so a café that never sets this gets the honest, more conservative
    # caveat rather than a false claim of reliability. See TableZone below
    # and spec's own "the UI will say which."
    mount_type = models.CharField(
        max_length=16, choices=MountType.choices, default=MountType.UNKNOWN,
        help_text=_("Affects how confidently table occupancy is reported for this camera's tables."),
    )

    class Meta:
        verbose_name = _("camera")
        verbose_name_plural = _("cameras")
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=["cafe", "name"], name="unique_camera_name_per_cafe"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.cafe_id})"

    # -- credentials ---------------------------------------------------------
    def set_password(self, raw_password: str) -> None:
        self.rtsp_password_encrypted = encrypt_secret(raw_password)

    def get_password(self) -> str:
        return decrypt_secret(self.rtsp_password_encrypted)

    def build_connection_url(self) -> str:
        """The URL actually used to open the stream, credentials embedded.

        OpenCV/FFmpeg have no separate RTSP auth parameter, so this is the only
        way to authenticate. Never log or serialise this value directly --
        pass it through `scv_contracts.redact.redact_rtsp_credentials` first.
        """
        if not self.rtsp_username:
            return self.rtsp_url
        password = self.get_password()
        scheme, _sep, rest = self.rtsp_url.partition("://")
        credentials = self.rtsp_username if not password else f"{self.rtsp_username}:{password}"
        return f"{scheme}://{credentials}@{rest}"

    # -- health ---------------------------------------------------------------
    @property
    def is_stale(self) -> bool:
        """True when the camera claims to be connected but has gone quiet.

        A stalled stream (TCP still up, no frames arriving) is the failure mode
        that a status field alone cannot catch -- `connection_status` only
        changes when the worker notices and reports it, which can lag behind
        reality. The dashboard uses this to show "connected" as suspect rather
        than trusting it blindly.
        """
        if self.connection_status != self.ConnectionStatus.CONNECTED or not self.last_frame_at:
            return False
        from django.utils import timezone

        return (timezone.now() - self.last_frame_at).total_seconds() > 30


class Zone(BaseModel):
    """An entrance/exit line on one camera's frame (spec §4).

    A directed line segment, not a polygon: every example in the spec of a
    "zone" resolves to "customer crosses a line" -- a threshold, not an area.
    Table zones (Phase 9) are a genuinely different shape (an area to be
    occupied, not a line to be crossed) and will be their own model rather
    than a forced generalisation of this one.

    No direct `cafe` field: a zone only ever exists in the context of its
    camera, so cafe-scoping is enforced through `camera__cafe_id` in
    querysets rather than denormalising a relationship that would need to
    stay in sync if a camera were ever reassigned -- not a supported
    operation today.

    Coordinates are pixels against the camera's own frame, at whatever
    resolution the worker reported (`Camera.resolution_width/height`) when the
    admin drew the line. If a camera's resolution later changes -- a swapped
    camera, a different stream profile -- an existing zone's coordinates
    become meaningless; re-drawing it is the admin's job, not something this
    system attempts to rescale automatically.
    """

    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="zones")
    name = models.CharField(max_length=120, default="Entrance")

    point_a_x = models.FloatField()
    point_a_y = models.FloatField()
    point_b_x = models.FloatField()
    point_b_y = models.FloatField()

    # A crossing from the negative side to the positive side of the directed
    # line point_a -> point_b counts as an entry when True, an exit when
    # False. Must agree with worker/zones.py:side_of_line's sign convention --
    # the worker is the only place this value is actually interpreted; the
    # backend only stores and serves it.
    entry_is_positive_side = models.BooleanField(default=True)

    is_active = models.BooleanField(
        default=True,
        help_text=_("Disable to stop entry/exit detection on this line without deleting it."),
    )

    class Meta:
        verbose_name = _("zone")
        verbose_name_plural = _("zones")
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.camera_id})"

    @property
    def point_a(self) -> tuple[float, float]:
        return (self.point_a_x, self.point_a_y)

    @property
    def point_b(self) -> tuple[float, float]:
        return (self.point_b_x, self.point_b_y)


class TableZone(BaseModel):
    """One physical table's rectangle on a camera's frame (spec §10).

    An area to be covered, not a line to be crossed -- genuinely a different
    shape from Zone above, hence its own model rather than a forced
    generalisation of one (see Zone's own docstring, which anticipated this).
    Axis-aligned, not an arbitrary polygon: table occupancy is already an
    approximation for anything but an overhead camera (Camera.mount_type),
    and a polygon editor would buy more apparent precision than the
    underlying detection can actually deliver -- see
    ai_worker/worker/tables.py's module docstring for why occupancy itself is
    a coarse box-overlap heuristic rather than a pinpoint location.

    No direct `cafe` field, same reasoning as Zone: a table only ever exists
    in the context of its camera, so cafe-scoping goes through
    `camera__cafe_id` rather than a denormalised relationship.
    """

    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="tables")
    name = models.CharField(max_length=120, default="Table")

    x1 = models.FloatField()
    y1 = models.FloatField()
    x2 = models.FloatField()
    y2 = models.FloatField()

    is_active = models.BooleanField(
        default=True,
        help_text=_("Disable to stop occupancy detection on this table without deleting it."),
    )

    class Meta:
        verbose_name = _("table")
        verbose_name_plural = _("tables")
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.camera_id})"
