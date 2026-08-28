"""Publisher resilience.

The properties here decide what happens during the two failures a café install
actually experiences: Redis restarting, and the worker being killed.
"""
from __future__ import annotations

import redis

from scv_contracts import Event, EventType
from worker.publisher import MAX_BUFFERED_EVENTS, EventPublisher


def make_publisher(client) -> EventPublisher:
    publisher = EventPublisher.__new__(EventPublisher)
    publisher.stream_key = "test:events"
    publisher.maxlen = 1000
    publisher._client = client
    publisher._buffer = []
    return publisher


def event() -> Event:
    return Event(type=EventType.WORKER_HEARTBEAT, cafe_id="cafe-1", worker_id="worker-1")


class BrokenRedis:
    """A client that fails until `working` is set."""

    def __init__(self) -> None:
        self.working = False
        self.written: list[dict] = []

    def xadd(self, _stream, fields, **_kwargs):
        if not self.working:
            raise redis.ConnectionError("redis is down")
        self.written.append(fields)
        return b"1-0"

    def set(self, *_args, **_kwargs):
        if not self.working:
            raise redis.ConnectionError("redis is down")
        return True

    def ping(self):
        if not self.working:
            raise redis.ConnectionError("redis is down")
        return True

    def close(self):
        return None


def test_events_are_published_when_redis_is_up():
    client = BrokenRedis()
    client.working = True
    publisher = make_publisher(client)

    assert publisher.publish(event()) is True
    assert len(client.written) == 1
    assert publisher.buffered_count == 0


def test_events_are_buffered_while_redis_is_down():
    """A Redis restart must not lose the events captured during it."""
    client = BrokenRedis()
    publisher = make_publisher(client)

    assert publisher.publish(event()) is False
    assert publisher.buffered_count == 1
    assert client.written == []


def test_buffered_events_are_flushed_when_redis_returns():
    client = BrokenRedis()
    publisher = make_publisher(client)

    for _ in range(3):
        publisher.publish(event())
    assert publisher.buffered_count == 3

    client.working = True
    publisher.publish(event())

    assert publisher.buffered_count == 0
    assert len(client.written) == 4  # three buffered, then the new one


def test_buffered_events_keep_their_order():
    client = BrokenRedis()
    publisher = make_publisher(client)

    first, second = event(), event()
    publisher.publish(first)
    publisher.publish(second)

    client.working = True
    publisher.publish(event())

    written_ids = [fields["event_id"] for fields in client.written]
    assert written_ids[:2] == [first.event_id, second.event_id]


def test_the_buffer_is_bounded():
    """An outage must not turn into an out-of-memory kill."""
    client = BrokenRedis()
    publisher = make_publisher(client)

    for _ in range(MAX_BUFFERED_EVENTS + 50):
        publisher.publish(event())

    assert publisher.buffered_count == MAX_BUFFERED_EVENTS


def test_heartbeat_failure_is_reported_not_raised():
    publisher = make_publisher(BrokenRedis())
    assert publisher.heartbeat("worker-1") is False
