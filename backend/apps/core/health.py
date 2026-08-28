"""Component health checks (spec §27).

Each check answers one question, returns a small dict, and never raises. The
dashboard renders these directly, so the vocabulary is fixed:

    ok       - working
    degraded - working, but something needs attention
    down     - not working
"""
from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings
from django.db import connections
from django.db.utils import OperationalError

logger = logging.getLogger("smartcafe.health")

OK = "ok"
DEGRADED = "degraded"
DOWN = "down"

# A worker that has not published a heartbeat in this long is presumed dead.
WORKER_HEARTBEAT_TIMEOUT_SECONDS = 30


def _timed(fn) -> tuple[Any, float]:
    started = time.monotonic()
    result = fn()
    return result, round((time.monotonic() - started) * 1000, 2)


def check_database() -> dict[str, Any]:
    def probe() -> None:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

    try:
        _, latency_ms = _timed(probe)
    except OperationalError as exc:
        logger.error("database_unreachable error=%s", exc)
        return {"status": DOWN, "detail": "Database is unreachable."}
    except Exception as exc:  # pragma: no cover - driver-specific failures
        logger.exception("database_check_failed")
        return {"status": DOWN, "detail": str(exc)[:200]}
    return {"status": OK, "latency_ms": latency_ms}


def _redis_client():
    import redis

    return redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)


def check_redis() -> dict[str, Any]:
    try:
        client = _redis_client()
        _, latency_ms = _timed(client.ping)
    except Exception as exc:
        logger.error("redis_unreachable error=%s", type(exc).__name__)
        return {"status": DOWN, "detail": "Redis is unreachable."}
    return {"status": OK, "latency_ms": latency_ms}


def check_event_stream() -> dict[str, Any]:
    """Report the depth of the AI event stream.

    A growing backlog means the backend is ingesting slower than the worker
    produces -- the earliest visible symptom of an overloaded café server.
    """
    try:
        client = _redis_client()
        length = client.xlen(settings.EVENT_STREAM_KEY)
    except Exception:
        return {"status": DOWN, "detail": "Event stream is unreadable."}

    pending = int(length)
    status = OK
    detail = None
    if pending > settings.EVENT_STREAM_MAXLEN * 0.8:
        status = DEGRADED
        detail = "Event backlog is close to the stream cap; ingest is falling behind."
    return {"status": status, "stream_length": pending, **({"detail": detail} if detail else {})}


def check_ai_workers() -> dict[str, Any]:
    """Liveness of AI workers, derived from heartbeats they write to Redis.

    Phase 1 has no worker running yet, so 'no workers registered' is reported as
    degraded rather than down: the café dashboard still works without one.
    """
    try:
        client = _redis_client()
        keys = list(client.scan_iter(match="scv:worker:*:heartbeat", count=100))
    except Exception:
        return {"status": DOWN, "detail": "Cannot read worker heartbeats."}

    now = time.time()
    workers: list[dict[str, Any]] = []
    for key in keys:
        raw = client.get(key)
        if raw is None:
            continue
        name = key.decode().split(":")[2] if isinstance(key, bytes) else key.split(":")[2]
        try:
            beat_at = float(raw)
        except (TypeError, ValueError):
            continue
        age = now - beat_at
        workers.append(
            {
                "worker_id": name,
                "status": OK if age <= WORKER_HEARTBEAT_TIMEOUT_SECONDS else DOWN,
                "seconds_since_heartbeat": round(age, 1),
            }
        )

    if not workers:
        return {
            "status": DEGRADED,
            "detail": "No AI worker has registered a heartbeat.",
            "workers": [],
        }
    overall = OK if all(w["status"] == OK for w in workers) else DEGRADED
    return {"status": overall, "workers": workers}


CRITICAL_COMPONENTS = ("database", "redis")


def collect(include_workers: bool = True) -> dict[str, Any]:
    components: dict[str, Any] = {
        "database": check_database(),
        "redis": check_redis(),
    }
    if components["redis"]["status"] == OK:
        components["event_stream"] = check_event_stream()
        if include_workers:
            components["ai_workers"] = check_ai_workers()

    statuses = {name: data["status"] for name, data in components.items()}
    if any(statuses.get(name) == DOWN for name in CRITICAL_COMPONENTS):
        overall = DOWN
    elif DOWN in statuses.values() or DEGRADED in statuses.values():
        overall = DEGRADED
    else:
        overall = OK

    return {
        "status": overall,
        "environment": settings.ENVIRONMENT,
        "version": settings.SPECTACULAR_SETTINGS["VERSION"],
        "components": components,
    }
