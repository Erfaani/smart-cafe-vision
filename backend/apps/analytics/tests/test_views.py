from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from apps.analytics.models import DailyStat

pytestmark = pytest.mark.django_db


def make_stat(cafe, **overrides) -> DailyStat:
    defaults = {"cafe": cafe, "date": date(2026, 6, 1), "visitor_count": 1}
    defaults.update(overrides)
    return DailyStat.objects.create(**defaults)


def test_list_requires_authentication(api):
    assert api.get(reverse("daily-stat-list")).status_code == 401


def test_list_is_scoped_to_the_callers_cafe(auth_api, cafe, other_cafe):
    make_stat(cafe, date=date(2026, 6, 1))
    make_stat(other_cafe, date=date(2026, 6, 1))

    body = auth_api.get(reverse("daily-stat-list")).json()
    assert len(body) == 1


def test_staff_role_can_read(api, cafe, staff):
    from rest_framework_simplejwt.tokens import RefreshToken

    make_stat(cafe)
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(staff).access_token}")
    assert api.get(reverse("daily-stat-list")).status_code == 200


def test_list_is_not_paginated(auth_api, cafe):
    for day in range(1, 6):
        make_stat(cafe, date=date(2026, 6, day))

    body = auth_api.get(reverse("daily-stat-list")).json()
    assert isinstance(body, list)
    assert len(body) == 5


def test_list_is_ordered_ascending_by_date(auth_api, cafe):
    make_stat(cafe, date=date(2026, 6, 3))
    make_stat(cafe, date=date(2026, 6, 1))
    make_stat(cafe, date=date(2026, 6, 2))

    body = auth_api.get(reverse("daily-stat-list")).json()
    assert [item["date"] for item in body] == ["2026-06-01", "2026-06-02", "2026-06-03"]


def test_start_and_end_filter_the_date_range(auth_api, cafe):
    make_stat(cafe, date=date(2026, 5, 31))
    make_stat(cafe, date=date(2026, 6, 1))
    make_stat(cafe, date=date(2026, 6, 15))
    make_stat(cafe, date=date(2026, 7, 1))

    response = auth_api.get(
        reverse("daily-stat-list"), {"start": "2026-06-01", "end": "2026-06-30"}
    )
    body = response.json()
    assert [item["date"] for item in body] == ["2026-06-01", "2026-06-15"]


def test_list_is_read_only(auth_api, cafe):
    response = auth_api.post(reverse("daily-stat-list"), {"date": "2026-06-01"}, format="json")
    assert response.status_code == 405
