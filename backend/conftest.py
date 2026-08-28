"""Shared pytest fixtures."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.tenants.models import Cafe

User = get_user_model()

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def cafe(db) -> Cafe:
    return Cafe.objects.create(name="Café Central", timezone="Europe/Berlin", seating_capacity=30)


@pytest.fixture
def other_cafe(db) -> Cafe:
    return Cafe.objects.create(name="Second Branch", seating_capacity=20)


@pytest.fixture
def owner(db, cafe) -> User:
    return User.objects.create_user(
        email="owner@example.com", password=PASSWORD, role=User.Role.OWNER, cafe=cafe
    )


@pytest.fixture
def staff(db, cafe) -> User:
    return User.objects.create_user(
        email="staff@example.com", password=PASSWORD, role=User.Role.STAFF, cafe=cafe
    )


@pytest.fixture
def superuser_owner(db, cafe) -> User:
    """Exactly what `manage.py bootstrap` produces: a Django superuser that is
    *also* scoped to one café. This is the account every fresh install starts
    with, and the fixture exists because a bug (CafeScopedCreateMixin's whole
    reason for existing) was invisible to the test suite until a real
    end-to-end run used this exact account shape instead of a plain
    non-superuser `owner`.
    """
    return User.objects.create_superuser(
        email="bootstrap-owner@example.com", password=PASSWORD, role=User.Role.OWNER, cafe=cafe
    )


@pytest.fixture
def api():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def auth_api(api, owner):
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(owner).access_token
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api


@pytest.fixture
def superuser_auth_api(api, superuser_owner):
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(superuser_owner).access_token
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api
