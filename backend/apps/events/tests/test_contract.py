"""The event contract is a promise to the AI worker; these tests hold it."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from scv_contracts import CONTRACT_VERSION, ContractError, Event, EventType


def test_round_trip_through_stream_fields():
    event = Event(
        type=EventType.PERSON_ENTERED,
        cafe_id="8f0d2b1e-0000-4000-8000-000000000001",
        camera_id="8f0d2b1e-0000-4000-8000-000000000002",
        worker_id="worker-1",
        payload={"track_id": 27, "zone": "entrance"},
    )

    raw = event.to_stream_fields()
    assert all(isinstance(v, str) for v in raw.values()), "XADD accepts strings only"

    decoded = Event.from_stream_fields({k.encode(): v.encode() for k, v in raw.items()})
    assert decoded.event_id == event.event_id
    assert decoded.type is EventType.PERSON_ENTERED
    assert decoded.payload == {"track_id": 27, "zone": "entrance"}
    assert decoded.occurred_at == event.occurred_at


def test_timestamp_must_be_timezone_aware():
    """A naive timestamp is ambiguous across DST and would corrupt stay times."""
    with pytest.raises(ContractError, match="timezone-aware"):
        Event(type=EventType.WORKER_HEARTBEAT, cafe_id="c", occurred_at=datetime(2026, 1, 1, 12, 0))


def test_timestamp_is_normalised_to_utc():
    tehran = timezone(timedelta(hours=3, minutes=30))
    event = Event(
        type=EventType.WORKER_HEARTBEAT,
        cafe_id="c",
        occurred_at=datetime(2026, 1, 1, 12, 0, tzinfo=tehran),
    )
    assert event.occurred_at.tzinfo == UTC
    assert event.occurred_at.hour == 8 and event.occurred_at.minute == 30


def test_camera_scoped_events_require_a_camera():
    with pytest.raises(ContractError, match="requires camera_id"):
        Event(type=EventType.PERSON_EXITED, cafe_id="c")


@pytest.mark.parametrize("event_type", [EventType.TABLE_OCCUPIED, EventType.TABLE_RELEASED])
def test_table_events_require_a_camera(event_type):
    """A table only ever exists on one camera's frame (spec §10), same
    reasoning as an entrance/exit zone."""
    with pytest.raises(ContractError, match="requires camera_id"):
        Event(type=event_type, cafe_id="c")


def test_worker_events_do_not_require_a_camera():
    event = Event(type=EventType.WORKER_STARTED, cafe_id="c")
    assert event.camera_id is None


@pytest.mark.parametrize(
    "forbidden_key",
    ["face", "face_embedding", "embedding", "name", "phone", "image", "crop", "thumbnail"],
)
def test_payload_rejects_identifying_data(forbidden_key):
    """The privacy promise (spec §26) is enforced, not merely documented."""
    with pytest.raises(ContractError, match="anonymous data only"):
        Event(
            type=EventType.PERSON_DETECTED,
            cafe_id="c",
            camera_id="cam",
            payload={forbidden_key: "anything"},
        )


def test_payload_rejects_identifying_data_case_insensitively():
    with pytest.raises(ContractError):
        Event(
            type=EventType.PERSON_DETECTED,
            cafe_id="c",
            camera_id="cam",
            payload={"Face_Embedding": [0.1]},
        )


def test_unknown_event_type_is_rejected():
    with pytest.raises(ContractError, match="Unknown event type"):
        Event.from_dict({"type": "customer_named", "cafe_id": "c"})


def test_schema_version_mismatch_fails_loudly():
    """A worker and backend on different contracts must not half-understand each other."""
    payload = {
        "schema_version": CONTRACT_VERSION + 1,
        "type": EventType.WORKER_HEARTBEAT.value,
        "cafe_id": "c",
    }
    with pytest.raises(ContractError, match="not supported"):
        Event.from_dict(payload)


def test_cafe_id_is_required():
    with pytest.raises(ContractError, match="cafe_id is required"):
        Event(type=EventType.WORKER_HEARTBEAT, cafe_id="")


def test_payload_may_be_a_json_string_from_the_stream():
    event = Event.from_dict(
        {
            "type": EventType.CAMERA_STATS.value,
            "cafe_id": "c",
            "camera_id": "cam",
            "payload": '{"fps": 9.8}',
        }
    )
    assert event.payload == {"fps": 9.8}


def test_payload_string_values_are_scrubbed_of_rtsp_credentials():
    """FFmpeg/OpenCV echo the full connection URL, password included, into their
    error strings. A camera error landing in a payload is expected, so the
    contract scrubs it rather than trusting every call site to remember to.
    """
    event = Event(
        type=EventType.CAMERA_DISCONNECTED,
        cafe_id="c",
        camera_id="cam",
        payload={
            "reason": "connect_failed",
            "error": "rtsp://admin:hunter2@192.168.1.64:554/live: Connection refused",
        },
    )
    assert "hunter2" not in event.payload["error"]
    assert "192.168.1.64" in event.payload["error"]
    assert event.payload["reason"] == "connect_failed"
