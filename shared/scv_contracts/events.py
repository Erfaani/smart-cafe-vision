"""The AI worker → backend event contract.

Design rules that this module enforces, because getting them wrong is expensive
once a café is running:

1. **Every event carries its own wall-clock timestamp.** The worker stamps
   `occurred_at` when the frame was observed, not when the backend read it. Stay
   duration is derived from these timestamps, never from frame counts or from
   the ingest time, so a GPU stall or a slow queue cannot distort a customer's
   measured stay (spec §5, §22).

2. **Every event has a stable `event_id`.** The bus is at-least-once: a consumer
   restart can redeliver. Handlers deduplicate on `event_id`.

3. **No personal data may travel on this bus.** Payloads carry geometry, track
   ids and timings. Never faces, crops, embeddings, or names (spec §26).

4. **The schema is versioned.** A worker and a backend on different versions
   must fail loudly at ingest rather than silently misinterpret a field.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from scv_contracts.redact import redact_rtsp_credentials

CONTRACT_VERSION = 1


class EventType(StrEnum):
    """Every message the AI worker is allowed to emit."""

    # --- worker lifecycle -------------------------------------------------
    WORKER_STARTED = "worker_started"
    WORKER_STOPPED = "worker_stopped"
    WORKER_HEARTBEAT = "worker_heartbeat"

    # --- camera lifecycle (spec §17) --------------------------------------
    CAMERA_CONNECTED = "camera_connected"
    CAMERA_DISCONNECTED = "camera_disconnected"
    CAMERA_STATS = "camera_stats"

    # --- people (anonymous track ids only) --------------------------------
    PERSON_DETECTED = "person_detected"
    PERSON_ENTERED = "person_entered"
    PERSON_EXITED = "person_exited"

    # --- tables (spec §10) -------------------------------------------------
    TABLE_OCCUPIED = "table_occupied"
    TABLE_RELEASED = "table_released"


#: Event types whose payload must identify a camera.
CAMERA_SCOPED_EVENTS = frozenset(
    {
        EventType.CAMERA_CONNECTED,
        EventType.CAMERA_DISCONNECTED,
        EventType.CAMERA_STATS,
        EventType.PERSON_DETECTED,
        EventType.PERSON_ENTERED,
        EventType.PERSON_EXITED,
        EventType.TABLE_OCCUPIED,
        EventType.TABLE_RELEASED,
    }
)

#: Keys that must never appear in a payload. Enforced, not merely documented:
#: a future contributor adding a "face" field should hit an exception in tests.
FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "face",
        "faces",
        "face_embedding",
        "embedding",
        "embeddings",
        "identity",
        "name",
        "customer_name",
        "phone",
        "email",
        "image",
        "frame",
        "crop",
        "thumbnail",
    }
)


class ContractError(ValueError):
    """Raised when a message does not satisfy the event contract."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=UTC)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractError(f"occurred_at is not an ISO-8601 timestamp: {value!r}") from exc
    else:
        raise ContractError(f"occurred_at has unsupported type {type(value).__name__}")

    if parsed.tzinfo is None:
        # A naive timestamp is ambiguous across the café's DST boundary; the
        # worker always sends UTC, so refuse rather than guess.
        raise ContractError("occurred_at must be timezone-aware (send UTC).")
    return parsed.astimezone(UTC)


@dataclass(slots=True)
class Event:
    """One immutable observation produced by the AI worker."""

    type: EventType
    cafe_id: str
    occurred_at: datetime = field(default_factory=utcnow)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    camera_id: str | None = None
    worker_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        self.type = EventType(self.type)
        if not self.cafe_id:
            raise ContractError("cafe_id is required on every event.")
        self.occurred_at = _parse_timestamp(self.occurred_at)
        if self.type in CAMERA_SCOPED_EVENTS and not self.camera_id:
            raise ContractError(f"{self.type} requires camera_id.")
        _assert_payload_is_anonymous(self.payload)
        # Defense in depth: FFmpeg/OpenCV echo the full connection URL --
        # including the password -- into their error strings. A camera error
        # message landing in a payload is a normal, expected path (see
        # camera_disconnected), so it is scrubbed here rather than trusted to
        # every call site that builds one.
        self.payload = {
            key: redact_rtsp_credentials(value) if isinstance(value, str) else value
            for key, value in self.payload.items()
        }

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "type": str(self.type),
            "cafe_id": self.cafe_id,
            "camera_id": self.camera_id,
            "worker_id": self.worker_id,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload,
        }

    def to_stream_fields(self) -> dict[str, str]:
        """Flat string map for XADD. Payload travels as a JSON blob."""
        data = self.to_dict()
        return {
            "schema_version": str(data["schema_version"]),
            "event_id": data["event_id"],
            "type": data["type"],
            "cafe_id": data["cafe_id"],
            "camera_id": data["camera_id"] or "",
            "worker_id": data["worker_id"] or "",
            "occurred_at": data["occurred_at"],
            "payload": json.dumps(data["payload"], separators=(",", ":")),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        version = int(data.get("schema_version", CONTRACT_VERSION))
        if version != CONTRACT_VERSION:
            raise ContractError(
                f"Event schema version {version} is not supported by this build "
                f"(expected {CONTRACT_VERSION}). Upgrade the worker and the backend together."
            )
        raw_type = data.get("type")
        try:
            event_type = EventType(raw_type)
        except ValueError as exc:
            raise ContractError(f"Unknown event type {raw_type!r}.") from exc

        payload = data.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload) if payload else {}
            except json.JSONDecodeError as exc:
                raise ContractError("payload is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ContractError("payload must be a JSON object.")

        return cls(
            type=event_type,
            cafe_id=str(data.get("cafe_id") or ""),
            occurred_at=data.get("occurred_at") or utcnow(),
            event_id=str(data.get("event_id") or uuid.uuid4()),
            camera_id=(data.get("camera_id") or None),
            worker_id=(data.get("worker_id") or None),
            payload=payload,
            schema_version=version,
        )

    @classmethod
    def from_stream_fields(cls, fields: dict[Any, Any]) -> Event:
        """Decode a Redis stream entry (bytes keys/values are handled)."""
        decoded = {
            (k.decode() if isinstance(k, bytes) else k): (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in fields.items()
        }
        return cls.from_dict(decoded)


def _assert_payload_is_anonymous(payload: dict[str, Any]) -> None:
    """Reject payload keys that would turn anonymous tracking into surveillance.

    A guard rail, not a security boundary: it exists so that the privacy promise
    in the README is checked by the test suite instead of by memory.
    """
    if not isinstance(payload, dict):
        raise ContractError("payload must be a JSON object.")
    offending = sorted(FORBIDDEN_PAYLOAD_KEYS.intersection({str(k).lower() for k in payload}))
    if offending:
        raise ContractError(
            "payload contains personally identifying keys "
            f"{offending}; the event bus carries anonymous data only."
        )
