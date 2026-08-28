"""Long-running consumer: Redis stream → database.

Runs as its own container/process. Kept out of the web server so that a slow
ingest batch can never add latency to a dashboard request, and so a café can
restart the API without pausing event capture.

Operational contract:
  * survives Redis restarts with capped exponential backoff
  * exits cleanly on SIGTERM/SIGINT after acknowledging the current batch
  * acknowledges an entry only after it is committed, so a crash redelivers
    rather than loses
"""
from __future__ import annotations

import logging
import signal
import time
from typing import Any

import redis
from django.core.management.base import BaseCommand

from apps.events.bus import EventBus
from apps.events.ingest import ingest

logger = logging.getLogger("smartcafe.events")

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0


class Command(BaseCommand):
    help = "Consume AI worker events from the Redis stream into the database."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--consumer-name",
            default="ingest-1",
            help="Consumer name inside the group. Use a distinct name per process.",
        )
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument(
            "--once",
            action="store_true",
            help="Drain what is currently pending and exit (used by tests and by cron-style replay).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        consumer_name: str = options["consumer_name"]
        batch_size: int = options["batch_size"]
        run_once: bool = options["once"]

        self._running = True

        def _stop(signum, _frame):
            logger.info("consumer_shutdown_requested signal=%s", signum)
            self._running = False

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _stop)
            except ValueError:  # pragma: no cover - not on the main thread
                pass

        bus = EventBus()
        backoff = INITIAL_BACKOFF_SECONDS
        totals = {"stored": 0, "duplicate": 0, "rejected": 0}

        self.stdout.write(
            self.style.SUCCESS(
                f"Consuming stream {bus.stream!r} as {consumer_name!r} in group {bus.group!r}."
            )
        )

        while self._running:
            try:
                bus.ensure_group()
                processed_this_pass = 0
                for entry_id, event in bus.consume(consumer_name, count=batch_size):
                    result = ingest(event)
                    # Acknowledge after the transaction committed. A crash
                    # between commit and ack redelivers, and the unique
                    # event_id makes that a no-op.
                    bus.ack(entry_id)
                    processed_this_pass += 1

                    if result.stored:
                        totals["stored"] += 1
                    elif result.duplicate:
                        totals["duplicate"] += 1
                    else:
                        totals["rejected"] += 1
                        logger.warning(
                            "event_rejected type=%s reason=%s", event.type, result.reason
                        )

                    if not self._running:
                        break

                backoff = INITIAL_BACKOFF_SECONDS  # a successful pass resets it

                if run_once:
                    break
                if processed_this_pass == 0:
                    # Blocking read timed out; loop so signals are noticed.
                    continue

            except redis.RedisError as exc:
                logger.error(
                    "consumer_redis_error error=%s retry_in=%.1fs", type(exc).__name__, backoff
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            except Exception:
                logger.exception("consumer_unexpected_error")
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

        self.stdout.write(
            self.style.SUCCESS(
                "Consumer stopped. stored={stored} duplicate={duplicate} rejected={rejected}".format(
                    **totals
                )
            )
        )
