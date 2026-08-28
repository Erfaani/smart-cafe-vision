"""The published API schema must actually describe the API.

drf-spectacular degrades gracefully: an endpoint it cannot introspect is dropped
from the schema with a warning rather than an error. That is exactly the failure
worth catching in CI, because the result is documentation that looks complete
and silently is not.
"""
from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def schema() -> dict:
    from drf_spectacular.generators import SchemaGenerator

    return SchemaGenerator().get_schema(request=None, public=True)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/login/",
        "/api/v1/auth/refresh/",
        "/api/v1/auth/logout/",
        "/api/v1/auth/me/",
        "/api/v1/auth/password/",
        "/api/v1/auth/users/",
        "/api/v1/cafes/",
        "/api/v1/cafes/public/{slug}/",
        "/api/v1/events/",
        "/api/v1/events/ingest/",
        "/api/v1/events/bus-stats/",
        "/api/v1/cameras/",
        "/api/v1/cameras/{id}/",
        "/api/v1/cameras/{id}/test-connection/",
        "/api/v1/cameras/{id}/snapshot.jpg/",
        "/api/v1/cameras/{id}/stream.mjpg/",
        "/api/v1/cameras/{id}/detections/",
        "/api/v1/cameras/{id}/tracks/",
        "/api/v1/cameras/worker-config/",
    ],
)
def test_endpoint_is_documented(schema, path):
    assert path in schema["paths"], f"{path} is missing from the OpenAPI schema"


def test_login_documents_its_request_and_response(schema):
    operation = schema["paths"]["/api/v1/auth/login/"]["post"]
    assert "requestBody" in operation
    assert "200" in operation["responses"]


def test_schema_generation_emits_no_warnings(schema, capsys):
    """A warning here means an endpoint was quietly dropped."""
    assert "Warning" not in capsys.readouterr().err


def test_schema_endpoint_is_reachable(api):
    response = api.get(reverse("schema"))
    assert response.status_code == 200
