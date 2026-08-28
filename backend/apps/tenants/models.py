"""Tenant model.

v1 installs one café per server, but every domain table is keyed by café from
the first migration so a multi-site deployment (a chain, or one server serving
two branches over a VPN) needs no data surgery later.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.color import default_stay_color_stops, validate_color_stops
from apps.core.models import BaseModel

MAX_LOGO_UPLOAD_BYTES = 5 * 1024 * 1024


def validate_logo_size(value) -> None:
    """Reject an oversized logo before it reaches storage.

    Only an authenticated owner/manager can reach this field, so the risk is
    an insider filling disk with repeated large uploads rather than an
    outside attacker -- still worth a real, low, cap rather than trusting
    Django's default in-memory/temp-file threshold (2.5 MB) to double as a
    size limit, which it does not: that setting only decides where an
    upload is buffered while it streams in, not how large it may be.
    """
    if value.size > MAX_LOGO_UPLOAD_BYTES:
        raise ValidationError(
            f"Logo must be smaller than {MAX_LOGO_UPLOAD_BYTES // (1024 * 1024)} MB."
        )


class Cafe(BaseModel):
    """A single café or restaurant venue."""

    class Language(models.TextChoices):
        ENGLISH = "en", _("English")
        PERSIAN = "fa", _("Persian")

    name = models.CharField(max_length=120)
    slug = models.SlugField(
        max_length=140,
        unique=True,
        help_text=_("URL-safe identifier, e.g. used in /display/<slug>."),
    )
    logo = models.ImageField(
        upload_to="cafe-logos/", blank=True, null=True, validators=[validate_logo_size]
    )

    # Business logic runs in UTC; this is presentation only. Analytics group by
    # local day using this zone, which is why it belongs to the café and not to
    # the viewing user.
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        help_text=_("IANA name, e.g. Europe/Berlin or Asia/Tehran."),
    )
    default_language = models.CharField(
        max_length=5, choices=Language.choices, default=Language.ENGLISH
    )

    seating_capacity = models.PositiveIntegerField(
        default=40,
        validators=[MinValueValidator(1)],
        help_text=_("Used as the denominator for occupancy percentage."),
    )

    is_active = models.BooleanField(default=True)

    # Phase 6: an ordered list of {"seconds": int, "color": "#rrggbb"} stops.
    # A customer's box on the public display and their row on the dashboard
    # both derive their colour from this same list, by continuous linear
    # interpolation -- see apps/core/color.py, which owns both the shape
    # (validate_color_stops) and the interpolation (color_for_duration) so
    # this field is never trusted to hold anything that function cannot use.
    stay_color_stops = models.JSONField(
        default=default_stay_color_stops,
        validators=[validate_color_stops],
        help_text=_(
            "Colour stops for stay-time display, e.g. green when a customer "
            "just arrived, sliding to red the longer they stay."
        ),
    )

    # Privacy (spec §26): the text shown on the in-café notice and the display
    # page, so a venue can meet its local disclosure obligations.
    privacy_notice_en = models.TextField(
        blank=True,
        default=(
            "This café uses anonymous camera analytics to measure how busy it is. "
            "No faces are recognised, no identities are stored, and no footage is kept."
        ),
    )
    privacy_notice_fa = models.TextField(
        blank=True,
        default=(
            "این کافه از تحلیل تصویری ناشناس برای اندازه‌گیری شلوغی استفاده می‌کند. "
            "هیچ چهره‌ای شناسایی نمی‌شود، هیچ هویتی ذخیره نمی‌شود و هیچ تصویری نگهداری نمی‌شود."
        ),
    )

    class Meta:
        verbose_name = _("café")
        verbose_name_plural = _("cafés")
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self) -> str:
        base = slugify(self.name, allow_unicode=False) or "cafe"
        slug = base
        counter = 2
        while Cafe.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{counter}"
            counter += 1
        return slug

    def privacy_notice(self, language: str | None = None) -> str:
        language = language or self.default_language
        return self.privacy_notice_fa if language == self.Language.PERSIAN else self.privacy_notice_en
