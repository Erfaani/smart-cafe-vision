from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.events import ingest as ingest_module
from apps.events.ingest import ingest, ingest_many, register_projection
from apps.events.models import TrackingEvent
from scv_contracts import Event, EventType

pytestmark = pytest.mark.django_db


def make_event(cafe, **overrides) -> Event:
    defaults = {
        "type": EventType.WORKER_HEARTBEAT,
        "cafe_id": str(cafe.id),
        "worker_id": "worker-1",
        "payload": {"fps": 9.5},
    }
    defaults.update(overrides)
    return Event(**defaults)


def test_event_is_stored_with_the_workers_timestamp(cafe):
    observed_at = timezone.now() - timedelta(seconds=42)
    result = ingest(make_event(cafe, occurred_at=observed_at))

    assert result.stored
    record = TrackingEvent.objects.get()
    # Stay-time correctness depends on this: we store when the worker SAW it,
    # not when we happened to read it off the queue.
    assert abs((record.occurred_at - observed_at).total_seconds()) < 0.001
    assert record.ingest_lag_seconds > 40


def test_redelivery_is_idempotent(cafe):
    event = make_event(cafe)

    first = ingest(event)
    second = ingest(event)

    assert first.stored
    assert second.duplicate
    assert TrackingEvent.objects.count() == 1


def test_event_for_an_unknown_cafe_is_rejected_not_stored():
    event = Event(type=EventType.WORKER_HEARTBEAT, cafe_id=str(uuid.uuid4()))
    result = ingest(event)
    assert result.rejected and "unknown cafe" in result.reason
    assert TrackingEvent.objects.count() == 0


def test_event_with_a_non_uuid_cafe_is_rejected():
    result = ingest(Event(type=EventType.WORKER_HEARTBEAT, cafe_id="not-a-uuid"))
    assert result.rejected


def test_projection_runs_for_its_event_type(cafe):
    # Snapshot and restore the exact prior list, rather than .clear()-ing it:
    # app registration happens once per process, so several real apps
    # (cameras, sessions, tables, and likely more as the roadmap continues)
    # already register their own projections here by the time this test
    # runs, on event types that keep gaining new owners phase over phase.
    # Blindly clearing would delete whichever of those is registered on
    # WORKER_STARTED for the rest of the test session -- this is the bug a
    # much earlier version of this test actually hit, once Phase 9 claimed
    # the event type it had been using.
    key = str(EventType.WORKER_STARTED)
    previous = list(ingest_module._projections[key])
    seen: list[str] = []
    register_projection(EventType.WORKER_STARTED, lambda event, record: seen.append(str(event.type)))
    try:
        ingest(make_event(cafe, type=EventType.WORKER_STARTED))
        ingest(make_event(cafe, type=EventType.WORKER_HEARTBEAT))
    finally:
        ingest_module._projections[key][:] = previous

    assert seen == ["worker_started"]


def test_a_failing_projection_rolls_back_the_event(cafe):
    """Nothing is acknowledged half-done: a failed projection means redelivery."""

    def explode(event, record):
        raise RuntimeError("projection failed")

    key = str(EventType.WORKER_STOPPED)
    previous = list(ingest_module._projections[key])
    register_projection(EventType.WORKER_STOPPED, explode)
    try:
        with pytest.raises(RuntimeError):
            ingest(make_event(cafe, type=EventType.WORKER_STOPPED))
    finally:
        ingest_module._projections[key][:] = previous

    assert TrackingEvent.objects.count() == 0


def test_ingest_many_reports_a_tally(cafe):
    duplicated = make_event(cafe)
    tally = ingest_many([make_event(cafe), duplicated, duplicated])
    assert tally == {"stored": 2, "duplicate": 1, "rejected": 0}


# --------------------------------------------------------------------------- #
# HTTP ingest endpoint
# --------------------------------------------------------------------------- #
def worker_headers(settings) -> dict[str, str]:
    return {"HTTP_X_WORKER_TOKEN": settings.AI_WORKER_TOKEN}


def test_http_ingest_requires_the_worker_token(api, cafe):
    response = api.post(reverse("event-ingest"), make_event(cafe).to_dict(), format="json")
    assert response.status_code == 403
    assert TrackingEvent.objects.count() == 0


def test_http_ingest_rejects_a_wrong_token(api, cafe):
    response = api.post(
        reverse("event-ingest"),
        make_event(cafe).to_dict(),
        format="json",
        HTTP_X_WORKER_TOKEN="wrong",
    )
    assert response.status_code == 403


def test_http_ingest_accepts_a_batch(api, cafe, settings):
    events = [make_event(cafe).to_dict() for _ in range(3)]
    response = api.post(
        reverse("event-ingest"), events, format="json", **worker_headers(settings)
    )
    assert response.status_code == 202
    assert response.json()["stored"] == 3
    assert TrackingEvent.objects.count() == 3


def test_http_ingest_reports_contract_violations(api, cafe, settings):
    good = make_event(cafe).to_dict()
    bad = {**good, "event_id": str(uuid.uuid4()), "type": "person_named"}
    response = api.post(
        reverse("event-ingest"), [good, bad], format="json", **worker_headers(settings)
    )
    assert response.status_code == 202
    body = response.json()
    assert body["stored"] == 1
    assert len(body["errors"]) == 1


def test_http_ingest_refuses_an_oversized_batch(api, cafe, settings):
    payload = [make_event(cafe).to_dict() for _ in range(2)] * 300
    response = api.post(
        reverse("event-ingest"), payload, format="json", **worker_headers(settings)
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "batch_too_large"


def test_event_list_is_scoped_to_the_callers_cafe(auth_api, cafe, other_cafe):
    ingest(make_event(cafe))
    ingest(Event(type=EventType.WORKER_HEARTBEAT, cafe_id=str(other_cafe.id)))

    results = auth_api.get(reverse("tracking-event-list")).json()["results"]
    assert len(results) == 1
