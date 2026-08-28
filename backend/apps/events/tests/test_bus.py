"""Event bus behaviour, against an in-process Redis (fakeredis).

The properties tested here are the ones that decide whether a café's analytics
survive an ordinary restart, so they are worth pinning down before any camera
code exists.
"""
from __future__ import annotations

from itertools import islice

import pytest

from apps.events.bus import EventBus
from scv_contracts import Event, EventType


@pytest.fixture
def bus():
    import fakeredis

    client = fakeredis.FakeRedis()
    return EventBus(client=client, stream="test:events", group="test-group", maxlen=1000)


def event(cafe_id: str = "cafe-1", **kwargs) -> Event:
    return Event(type=EventType.WORKER_HEARTBEAT, cafe_id=cafe_id, **kwargs)


def drain(bus: EventBus, consumer: str, count: int = 100) -> list:
    """Read everything currently available, without blocking.

    Production passes a block timeout so an idle consumer parks on the socket
    instead of spinning; a test has no producer coming, so it reads
    non-blockingly and returns immediately.
    """
    return list(bus.consume(consumer, count=count, block_ms=None))


def test_published_event_round_trips(bus):
    published = event(payload={"fps": 12})
    bus.publish(published)

    received = drain(bus, "consumer-a")
    assert len(received) == 1
    _entry_id, decoded = received[0]
    assert decoded.event_id == published.event_id
    assert decoded.payload == {"fps": 12}


def test_events_published_while_no_consumer_is_running_are_not_lost(bus):
    """The whole reason for choosing Streams over pub/sub."""
    bus.ensure_group()
    for _ in range(5):
        bus.publish(event())

    # Consumer starts only now, after every event was already published.
    received = drain(bus, "late-consumer")
    assert len(received) == 5


def test_unacknowledged_entries_are_redelivered_to_the_same_consumer(bus):
    bus.publish(event())

    first_pass = drain(bus, "consumer-a")
    assert len(first_pass) == 1  # taken, but deliberately not acknowledged

    # Simulates the consumer crashing before ack and restarting.
    second_pass = drain(bus, "consumer-a")
    assert len(second_pass) == 1
    assert second_pass[0][1].event_id == first_pass[0][1].event_id


def test_acknowledged_entries_are_not_redelivered(bus):
    bus.publish(event())

    for entry_id, _decoded in drain(bus, "consumer-a"):
        bus.ack(entry_id)

    assert drain(bus, "consumer-a") == []


def test_an_entry_goes_to_exactly_one_consumer_in_the_group(bus):
    """Two ingest processes must not each store the same event."""
    for _ in range(10):
        bus.publish(event())

    first_ids = [e.event_id for _, e in drain(bus, "consumer-a")]
    second_ids = [e.event_id for _, e in drain(bus, "consumer-b")]

    assert len(first_ids) == 10
    assert set(first_ids).isdisjoint(second_ids)


def test_two_consumers_share_the_backlog(bus):
    """Horizontal scale: a second ingest process picks up half the work."""
    for _ in range(10):
        bus.publish(event())

    # islice stops after one batch instead of draining, which is what a running
    # consumer does between acknowledgements.
    first = list(islice(bus.consume("consumer-a", count=5, block_ms=None), 5))
    second = list(islice(bus.consume("consumer-b", count=5, block_ms=None), 5))

    assert len(first) == len(second) == 5
    assert len({e.event_id for _, e in first} | {e.event_id for _, e in second}) == 10


def test_a_malformed_entry_is_dropped_without_wedging_the_stream(bus):
    bus.ensure_group()
    # An entry written by something that does not honour the contract.
    bus.client.xadd("test:events", {"type": "garbage", "cafe_id": "cafe-1"})
    good = event()
    bus.publish(good)

    received = drain(bus, "consumer-a")

    assert [e.event_id for _, e in received] == [good.event_id]


def test_stats_report_stream_depth(bus):
    bus.ensure_group()
    for _ in range(3):
        bus.publish(event())

    stats = bus.stats()
    assert stats["length"] == 3
    assert stats["stream"] == "test:events"


def test_ensure_group_is_idempotent(bus):
    bus.ensure_group()
    bus.ensure_group()  # must not raise BUSYGROUP
