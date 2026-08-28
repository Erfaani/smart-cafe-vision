"""One-command first-run setup.

The installation guide has a single step for "make the system usable": this
command. It is idempotent, so a technician who runs it twice on site does not
create a second café or reset a password by accident.
"""
from __future__ import annotations

import secrets
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tenants.models import Cafe

User = get_user_model()


class Command(BaseCommand):
    help = "Create the initial café and owner account (idempotent)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--cafe-name", default="My Café")
        parser.add_argument("--slug", default="", help="Defaults to a slug of the café name.")
        parser.add_argument("--timezone", default="UTC", dest="tz")
        parser.add_argument("--language", default="en", choices=["en", "fa"])
        parser.add_argument("--seating-capacity", type=int, default=40)
        parser.add_argument("--email", required=True, help="Owner login email.")
        parser.add_argument(
            "--password",
            default="",
            help="Owner password. Generated and printed once if omitted.",
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        email = options["email"].strip().lower()
        if not email:
            raise CommandError("--email is required.")

        cafe, cafe_created = self._resolve_cafe(options)

        generated_password = ""
        user = User.objects.filter(email=email).first()
        if user is None:
            password = options["password"] or self._generate_password()
            generated_password = "" if options["password"] else password
            user = User.objects.create_superuser(
                email=email,
                password=password,
                full_name="Café Owner",
                role=User.Role.OWNER,
                cafe=cafe,
            )
            user_created = True
        else:
            user_created = False
            if user.cafe_id is None:
                user.cafe = cafe
                user.save(update_fields=["cafe", "updated_at"])

        self.stdout.write(self.style.SUCCESS("Smart Café Vision is ready."))
        self.stdout.write(
            f"  Café:    {cafe.name} (slug: {cafe.slug}) "
            f"[{'created' if cafe_created else 'existing'}]"
        )
        self.stdout.write(
            f"  Owner:   {user.email} [{'created' if user_created else 'existing'}]"
        )
        if generated_password:
            self.stdout.write(
                self.style.WARNING(
                    f"  Password: {generated_password}\n"
                    "  This is shown once. Store it in your password manager and "
                    "change it after the first login."
                )
            )
        self.stdout.write(f"  Display: /display/{cafe.slug}")

    def _resolve_cafe(self, options: dict[str, Any]) -> tuple[Cafe, bool]:
        """Find the café by slug when given one, else by name; create if absent.

        Matching on an explicit slug first is what makes re-running the command
        with the same arguments a no-op instead of a second café.
        """
        slug = options["slug"].strip()
        existing = (
            Cafe.objects.filter(slug=slug).first()
            if slug
            else Cafe.objects.filter(name=options["cafe_name"]).first()
        )
        if existing:
            return existing, False

        cafe = Cafe(
            name=options["cafe_name"],
            timezone=options["tz"],
            default_language=options["language"],
            seating_capacity=options["seating_capacity"],
        )
        if slug:
            cafe.slug = slug
        cafe.save()
        return cafe, True

    @staticmethod
    def _generate_password() -> str:
        # 12 url-safe bytes clears the 10-character minimum with margin and is
        # still transcribable over the phone during an install.
        return secrets.token_urlsafe(12)
