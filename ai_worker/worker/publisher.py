"""Publishing side of the event bus.

The worker only ever writes to the stream; it never reads the database and never
calls the Django ORM. That separation is what allows the worker to run on a
different machine from the backend (a GPU box in the back office, the API on a
small always-on server) without any code change.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterable

import redis

from scv_contracts import Event
from scv_contracts.keys import worker_heartbeat_key

logger = logging.getLogger("scv.worker.publisher")

# If Redis is unreachable, hold this many events in memory before dropping the
# oldest. Bounded on purpose: an unbounded buffer turns a Redis outage into an
# out-of-memory kill, which is a worse failure than losing some detections.
MAX_BUFFERED_EVENTS = 5000


class EventPublisher:
    """Publishes events, tolerating a Redis that comes and goes."""

    def __init__(self, redis_url: str, stream_key: str, maxlen: int = 100_000) -> None:
        self.stream_key = stream_key
        self.maxlen = maxlen
        self._client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=3,
            socket_timeout=5,
            health_check_interval=30,
            retry_on_timeout=True,
        )
        self._buffer: list[Event] = []

    # -- publishing ---------------------------------------------------------
    def publish(self, event: Event) -> bool:
        """Publish one event. Buffers it locally if Redis is unavailable."""
        if self._buffer:
            self._flush()

        try:
            self._client.xadd(
                self.stream_key,
                event.to_stream_fields(),
                maxlen=self.maxlen,
                approximate=True,
            )
            return True
        except redis.RedisError as exc:
            logger.warning(
                "publish_failed type=%s error=%s buffered=%d",
                event.type,
                type(exc).__name__,
                len(self._buffer),
            )
            self._buffer_event(event)
            return False

    def publish_many(self, events: Iterable[Event]) -> int:
        return sum(1 for event in events if self.publish(event))

    def _buffer_event(self, event: Event) -> None:
        self._buffer.append(event)
        if len(self._buffer) > MAX_BUFFERED_EVENTS:
            dropped = len(self._buffer) - MAX_BUFFERED_EVENTS
            del self._buffer[:dropped]
            logger.error("event_buffer_overflow dropped=%d", dropped)

    def _flush(self) -> None:
        """Try to drain the local buffer. Stops at the first failure."""
        pending = self._buffer
        self._buffer = []
        for index, event in enumerate(pending):
            try:
                self._client.xadd(
                    self.stream_key,
                    event.to_stream_fields(),
                    maxlen=self.maxlen,
                    approximate=True,
                )
            except redis.RedisError:
                # Keep the rest, in order, for the next attempt.
                self._buffer = pending[index:] + self._buffer
                return
        if pending:
            logger.info("event_buffer_flushed count=%d", len(pending))

    @property
    def buffered_count(self) -> int:
        return len(self._buffer)

    # -- liveness -----------------------------------------------------------
    def heartbeat(self, worker_id: str, ttl_seconds: int = 60) -> bool:
        """Record that this worker is alive.

        A plain key with a TTL rather than an event: the backend's health page
        asks "is a worker alive right now?", and a key that expires on its own
        answers that correctly even if the worker was killed with SIGKILL.
        """
        try:
            self._client.set(
                worker_heartbeat_key(worker_id), str(time.time()), ex=ttl_seconds
            )
            return True
        except redis.RedisError as exc:
            logger.warning("heartbeat_failed error=%s", type(exc).__name__)
            return False

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except redis.RedisError:
            return False

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover - best effort on shutdown
            pass
