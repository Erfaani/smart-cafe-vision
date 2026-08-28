"""Publish a synthetic event onto the bus.

Phase 1 has no AI worker yet, so this is how the full path
(publish -> stream -> consumer -> database) is exercised on a real install
before a camera is ever connected. It is also the quickest way to tell whether
a support problem is in the worker or in the backend.
"""
from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.events.bus import EventBus
from apps.tenants.models import Cafe
from scv_contracts import Event, EventType


class Command(BaseCommand):
    help = "Publish a synthetic event to the Redis event stream."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--cafe", default="", help="Café slug. Defaults to the only café.")
        parser.add_argument("--type", default=EventType.WORKER_HEARTBEAT.value)
        parser.add_argument("--camera-id", default="")
        parser.add_argument("--count", type=int, default=1)

    def handle(self, *args: Any, **options: Any) -> None:
        slug = options["cafe"]
        cafe = Cafe.objects.filter(slug=slug).first() if slug else Cafe.objects.first()
        if cafe is None:
            raise CommandError(
                "No café found. Run `python manage.py bootstrap --email you@example.com` first."
            )

        try:
            event_type = EventType(options["type"])
        except ValueError as exc:
            valid = ", ".join(sorted(t.value for t in EventType))
            raise CommandError(f"Unknown event type. Valid types: {valid}") from exc

        bus = EventBus()
        for index in range(options["count"]):
            event = Event(
                type=event_type,
                cafe_id=str(cafe.id),
                camera_id=options["camera_id"] or None,
                worker_id="manual-cli",
                payload={"source": "emit_test_event", "sequence": index},
            )
            entry_id = bus.publish(event)
            self.stdout.write(f"published {event.type} entry={entry_id} event_id={event.event_id}")

        self.stdout.write(
            self.style.SUCCESS(
                f"{options['count']} event(s) published to {bus.stream!r}. "
                "Run `python manage.py consume_events --once` to ingest them."
            )
        )
