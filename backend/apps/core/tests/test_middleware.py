from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_every_response_carries_a_request_id(api):
    response = api.get(reverse("health"))
    assert response.headers["X-Request-ID"]


def test_an_upstream_request_id_is_preserved(api):
    response = api.get(reverse("health"), HTTP_X_REQUEST_ID="worker-frame-882")
    assert response.headers["X-Request-ID"] == "worker-frame-882"


def test_an_oversized_request_id_is_truncated(api):
    response = api.get(reverse("health"), HTTP_X_REQUEST_ID="x" * 500)
    assert len(response.headers["X-Request-ID"]) == 64
