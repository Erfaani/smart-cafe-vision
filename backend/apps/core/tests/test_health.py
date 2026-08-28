"""Health reporting (spec §27).

The dashboard's "is my café system OK?" panel is only as good as these, so the
degraded/down distinction is tested rather than assumed.
"""
from __future__ import annotations

import time
from unittest import mock

import pytest
from django.urls import reverse

from apps.core import health

pytestmark = pytest.mark.django_db


@pytest.fixture
def fake_redis(monkeypatch):
    import fakeredis

    client = fakeredis.FakeRedis()
    monkeypatch.setattr(health, "_redis_client", lambda: client)
    return client


def test_liveness_does_no_io(api):
    """A busy database must not make an orchestrator kill the backend."""
    with mock.patch.object(health, "check_database", side_effect=AssertionError("no I/O")):
        response = api.get(reverse("health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_check_reports_ok():
    assert health.check_database()["status"] == health.OK


def test_readiness_is_503_when_the_database_is_down(api, fake_redis):
    with mock.patch.object(
        health, "check_database", return_value={"status": health.DOWN, "detail": "gone"}
    ):
        response = api.get(reverse("readiness"))
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "down"
    assert body["components"]["database"]["status"] == "down"


def test_readiness_is_200_but_degraded_when_no_worker_is_running(api, fake_redis):
    """Phase 1 reality: no AI worker yet, and the café dashboard still works."""
    response = api.get(reverse("readiness"))
    assert response.status_code == 200
    body = response.json()
    assert body["components"]["ai_workers"]["status"] == "degraded"
    assert body["status"] == "degraded"


def test_a_recent_heartbeat_marks_a_worker_healthy(fake_redis):
    fake_redis.set("scv:worker:worker-1:heartbeat", str(time.time()))
    report = health.check_ai_workers()
    assert report["status"] == health.OK
    assert report["workers"][0]["worker_id"] == "worker-1"


def test_a_stale_heartbeat_marks_a_worker_down(fake_redis):
    stale = time.time() - (health.WORKER_HEARTBEAT_TIMEOUT_SECONDS + 5)
    fake_redis.set("scv:worker:worker-1:heartbeat", str(stale))
    report = health.check_ai_workers()
    assert report["workers"][0]["status"] == health.DOWN
    assert report["status"] == health.DEGRADED


def test_redis_being_unreachable_is_reported_not_raised(monkeypatch):
    def boom():
        raise ConnectionError("no redis")

    monkeypatch.setattr(health, "_redis_client", boom)
    assert health.check_redis()["status"] == health.DOWN


def test_readiness_exposes_no_cafe_or_customer_data(api, fake_redis, cafe):
    """Unauthenticated endpoint: it may reveal component status and nothing else."""
    body = api.get(reverse("readiness")).content.decode()
    assert cafe.name not in body
    assert str(cafe.id) not in body


def test_a_growing_backlog_is_reported_as_degraded(fake_redis, settings):
    settings.EVENT_STREAM_MAXLEN = 10
    for index in range(9):
        fake_redis.xadd(settings.EVENT_STREAM_KEY, {"n": str(index)})
    assert health.check_event_stream()["status"] == health.DEGRADED
