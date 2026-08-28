"""One-time historical rollup, for a café that already has CustomerSession
history from before Phase 8 shipped (or for reprocessing a range with
--force after fixing a bug in the rollup logic itself).

The scheduled task (apps.analytics.tasks.refresh_daily_stats) only ever
touches today and yesterday -- it is not the tool for filling in a year of
pre-existing data, hence this command. A technician runs it once during an
upgrade.
"""
from __future__ import annotations

import zoneinfo
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.analytics.models import DailyStat
from apps.analytics.rollups import compute_daily_stat
from apps.sessions.models import CustomerSession
from apps.tenants.models import Cafe


class Command(BaseCommand):
    help = "Compute DailyStat rows for a café's full CustomerSession history."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--cafe", default="", help="Café slug. Defaults to every active café."
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recompute days that already have a final row, not just missing/unfinished ones.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        cafes = [self._get_cafe(options["cafe"])] if options["cafe"] else list(Cafe.objects.filter(is_active=True))
        force: bool = options["force"]

        total_days = sum(self._backfill_one(cafe, force=force) for cafe in cafes)
        self.stdout.write(self.style.SUCCESS(f"Computed {total_days} daily stat row(s)."))

    def _get_cafe(self, slug: str) -> Cafe:
        try:
            return Cafe.objects.get(slug=slug)
        except Cafe.DoesNotExist as exc:
            raise CommandError(f"No café with slug {slug!r}.") from exc

    def _backfill_one(self, cafe: Cafe, *, force: bool) -> int:
        earliest = (
            CustomerSession.objects.filter(cafe=cafe)
            .order_by("entry_at")
            .values_list("entry_at", flat=True)
            .first()
        )
        if earliest is None:
            self.stdout.write(f"{cafe.name}: no sessions yet, nothing to backfill.")
            return 0

        tz = zoneinfo.ZoneInfo(cafe.timezone)
        start_date = earliest.astimezone(tz).date()
        end_date = timezone.now().astimezone(tz).date()

        existing_final = set(
            DailyStat.objects.filter(cafe=cafe, is_final=True).values_list("date", flat=True)
        )

        computed = 0
        current = start_date
        while current <= end_date:
            if force or current not in existing_final:
                compute_daily_stat(cafe, current)
                computed += 1
            current += timedelta(days=1)

        self.stdout.write(f"{cafe.name}: computed {computed} day(s) from {start_date} to {end_date}.")
        return computed
