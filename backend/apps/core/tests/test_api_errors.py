"""Every API error uses one envelope so clients need one error path."""
from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_unauthenticated_error_uses_the_envelope(api):
    body = api.get(reverse("cafe-list")).json()
    assert set(body) == {"error"}
    assert body["error"]["code"]
    assert body["error"]["message"]


def test_not_found_uses_the_envelope(auth_api):
    body = auth_api.get(reverse("cafe-detail", args=["missing-cafe"])).json()
    assert body["error"]["code"] == "not_found"


def test_validation_error_carries_field_detail(auth_api, cafe):
    body = auth_api.patch(
        reverse("cafe-detail", args=[cafe.slug]), {"timezone": "Nope/Nope"}, format="json"
    ).json()
    assert body["error"]["code"] == "invalid"
    assert "timezone" in body["error"]["detail"]
