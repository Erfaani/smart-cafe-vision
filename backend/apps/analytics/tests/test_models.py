from __future__ import annotations

from datetime import date

import pytest
from django.db import IntegrityError

from apps.analytics.models import DailyStat

pytestmark = pytest.mark.django_db


def make_stat(cafe, **overrides) -> DailyStat:
    defaults = {"cafe": cafe, "date": date(2026, 6, 1)}
    defaults.update(overrides)
    return DailyStat.objects.create(**defaults)


def test_one_row_per_cafe_per_day(cafe):
    make_stat(cafe, date=date(2026, 6, 1))
    with pytest.raises(IntegrityError):
        make_stat(cafe, date=date(2026, 6, 1))


def test_the_same_day_is_allowed_in_a_different_cafe(cafe, other_cafe):
    make_stat(cafe, date=date(2026, 6, 1))
    make_stat(other_cafe, date=date(2026, 6, 1))  # must not raise
