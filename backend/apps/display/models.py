"""DisplayMessage model (Phase 7, spec: "configurable funny messages in
Persian and English").

Deliberately untargeted: a message is a generic rotating line ("Did you know
our beans are roasted locally?"), never associated with a specific tracked
person or session. The public display already treats individual stay-time
data carefully (see apps/display/live.py's leaderboard, which shows durations
only, never a track id or camera) -- a message system that could reference
"the person who has been here 2 hours" would undo that by turning an
anonymous statistic into something the room could visibly point at.
"""
from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import CafeScopedModel


class DisplayMessage(CafeScopedModel):
    """One rotating line shown during the display's entertainment mode."""

    text_en = models.CharField(max_length=200)
    text_fa = models.CharField(max_length=200, blank=True, default="")
    is_active = models.BooleanField(
        default=True,
        help_text=_("Disable to remove a message from rotation without deleting it."),
    )

    class Meta:
        verbose_name = _("display message")
        verbose_name_plural = _("display messages")
        ordering = ("created_at",)

    def __str__(self) -> str:
        return self.text_en

    def text(self, language: str) -> str:
        """`text_fa` falls back to `text_en` when a café has not translated a
        message yet -- an empty line on the display would look broken,
        showing the wrong language does not."""
        return self.text_fa if language == "fa" and self.text_fa else self.text_en
