"""Abstract base models shared by every domain app."""
from __future__ import annotations

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Adds created/updated bookkeeping columns."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """UUID primary key.

    Used for anything a browser or the public display can reference. Sequential
    integer ids would let anyone reading the display page infer how many
    customers the café has served, which is exactly the kind of leak the privacy
    model is meant to avoid.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    """UUID primary key + timestamps."""

    class Meta:
        abstract = True


class CafeScopedModel(BaseModel):
    """Every tenant-owned record carries its café from the first migration.

    Retro-fitting a tenant key onto tables that already hold production data is
    the kind of migration that takes a café offline, so it is here from day one
    even though v1 ships single-tenant.
    """

    cafe = models.ForeignKey(
        "tenants.Cafe",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
    )

    class Meta:
        abstract = True
