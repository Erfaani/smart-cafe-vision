"""Redis Streams event bus.

Why Streams and not pub/sub — the decision this whole design rests on:

Pub/sub delivers to whoever is connected *right now*. Restart the backend to
apply a setting and every event published during those four seconds is gone. If
one of them was a `person_exited`, that customer's session never closes and the
café's stay-time analytics are wrong for the rest of the day, silently.

Streams persist entries, support consumer groups with explicit acknowledgement,
and let a restarted consumer pick up exactly where it stopped. The cost is a
capped memory buffer, which `EVENT_STREAM_MAXLEN` bounds.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import redis
from django.conf import settings

from scv_contracts import ContractError, Event

logger = logging.getLogger("smartcafe.events")

# Block this long waiting for new entries before returning control, so a
# consumer can notice shutdown signals promptly.
READ_BLOCK_MS = 5000

# XREADGROUP cursors: ">" delivers entries no consumer in the group has taken
# yet; any explicit id replays this consumer's own pending (unacknowledged)
# entries after that id.
LIVE_CURSOR = ">"
BACKLOG_CURSOR = "0"


def get_redis(url: str | None = None) -> redis.Redis:
    return redis.Redis.from_url(
        url or settings.REDIS_URL,
        socket_connect_timeout=5,
        socket_timeout=30,
        health_check_interval=30,
        retry_on_timeout=True,
    )


class EventBus:
    """Publish/consume side of the AI worker → backend channel."""

    def __init__(
        self,
        client: redis.Redis | None = None,
        *,
        stream: str | None = None,
        group: str | None = None,
        maxlen: int | None = None,
    ) -> None:
        self.client = client or get_redis()
        self.stream = stream or settings.EVENT_STREAM_KEY
        self.group = group or settings.EVENT_STREAM_GROUP
        self.maxlen = maxlen if maxlen is not None else settings.EVENT_STREAM_MAXLEN

    # -- producer ----------------------------------------------------------
    def publish(self, event: Event) -> str:
        """Append one event. Returns the stream entry id."""
        entry_id = self.client.xadd(
            self.stream,
            event.to_stream_fields(),
            maxlen=self.maxlen,
            approximate=True,  # trimming exactly costs more than it is worth
        )
        return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)

    # -- consumer ----------------------------------------------------------
    def ensure_group(self) -> None:
        """Create the consumer group, tolerating an existing one.

        `mkstream=True` so the backend can start before the worker has ever
        published anything, which is the normal order on a fresh install.
        """
        try:
            self.client.xgroup_create(self.stream, self.group, id="0", mkstream=True)
            logger.info("event_group_created stream=%s group=%s", self.stream, self.group)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def consume(
        self,
        consumer_name: str,
        *,
        count: int = 100,
        block_ms: int = READ_BLOCK_MS,
        claim_pending_first: bool = True,
    ) -> Iterator[tuple[str, Event]]:
        """Yield (entry_id, event) pairs. Acknowledge with `ack()` after handling.

        The first pass reads this consumer's own pending entries (cursor "0"):
        anything it took but crashed before acknowledging is redelivered, which
        is what makes a mid-batch crash survivable. Once that backlog drains the
        cursor switches to ">" for live entries.

        The generator returns when a blocking read times out, handing control
        back so the caller can check for a shutdown signal.
        """
        self.ensure_group()
        cursor = BACKLOG_CURSOR if claim_pending_first else LIVE_CURSOR

        while True:
            try:
                response = self.client.xreadgroup(
                    self.group,
                    consumer_name,
                    {self.stream: cursor},
                    count=count,
                    # Never block while draining the backlog: it is finite.
                    block=block_ms if cursor == LIVE_CURSOR else None,
                )
            except redis.ConnectionError as exc:
                # Redis restarting is an expected event on a café mini PC, not a
                # crash: let the caller decide how long to back off.
                logger.warning("event_bus_disconnected error=%s", exc)
                raise

            entries: list[tuple[Any, dict]] = []
            for _stream_name, items in response or []:
                entries.extend(items)

            if not entries:
                if cursor != LIVE_CURSOR:
                    # Backlog drained; from here on, only new entries.
                    cursor = LIVE_CURSOR
                    continue
                return

            for entry_id, fields in entries:
                entry = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                # While replaying the backlog the cursor must advance past each
                # entry. Leaving it at "0" re-reads the same unacknowledged
                # entries on every pass, which is an infinite loop rather than a
                # slow one -- a restarted consumer with a backlog would never
                # reach live traffic.
                if cursor != LIVE_CURSOR:
                    cursor = entry

                try:
                    event = Event.from_stream_fields(fields)
                except ContractError as exc:
                    # A malformed entry must never wedge the pipeline: log it,
                    # acknowledge it, move on.
                    logger.error("event_contract_violation entry=%s error=%s", entry, exc)
                    self.ack(entry)
                    continue
                yield entry, event

    def ack(self, *entry_ids: str) -> int:
        if not entry_ids:
            return 0
        return int(self.client.xack(self.stream, self.group, *entry_ids))

    # -- introspection ------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        try:
            length = int(self.client.xlen(self.stream))
        except redis.ResponseError:
            length = 0
        pending = 0
        try:
            info = self.client.xpending(self.stream, self.group)
            pending = int(info.get("pending", 0)) if isinstance(info, dict) else 0
        except redis.ResponseError:
            pass
        return {"stream": self.stream, "group": self.group, "length": length, "pending": pending}
