from __future__ import annotations

import pytest
from conftest import PASSWORD
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_login_returns_tokens_and_profile(api, owner):
    response = api.post(
        reverse("auth-login"), {"email": owner.email, "password": PASSWORD}, format="json"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access"] and body["refresh"]
    assert body["user"]["email"] == owner.email
    assert body["user"]["role"] == "owner"
    assert body["user"]["cafe_slug"] == owner.cafe.slug
    # The profile must never carry the password hash to the browser.
    assert "password" not in body["user"]


def test_login_is_case_insensitive_on_email(api, owner):
    response = api.post(
        reverse("auth-login"),
        {"email": owner.email.upper(), "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200


def test_login_with_wrong_password_returns_401_without_leaking_existence(api, owner):
    wrong_password = api.post(
        reverse("auth-login"), {"email": owner.email, "password": "nope"}, format="json"
    )
    unknown_user = api.post(
        reverse("auth-login"),
        {"email": "ghost@example.com", "password": "nope"},
        format="json",
    )
    assert wrong_password.status_code == unknown_user.status_code == 401
    # Identical message: an attacker must not be able to enumerate staff emails.
    assert wrong_password.json() == unknown_user.json()


def test_inactive_user_cannot_log_in(api, owner):
    owner.is_active = False
    owner.save(update_fields=["is_active"])
    response = api.post(
        reverse("auth-login"), {"email": owner.email, "password": PASSWORD}, format="json"
    )
    assert response.status_code == 401


def test_refresh_issues_a_new_access_token(api, owner):
    login = api.post(
        reverse("auth-login"), {"email": owner.email, "password": PASSWORD}, format="json"
    ).json()
    response = api.post(reverse("auth-refresh"), {"refresh": login["refresh"]}, format="json")
    assert response.status_code == 200
    assert response.json()["access"]


def test_me_requires_authentication(api):
    assert api.get(reverse("auth-me")).status_code == 401


def test_me_returns_the_current_profile(auth_api, owner):
    response = auth_api.get(reverse("auth-me"))
    assert response.status_code == 200
    assert response.json()["email"] == owner.email


def test_password_change_requires_the_current_password(auth_api):
    response = auth_api.post(
        reverse("auth-password"),
        {"current_password": "wrong", "new_password": "a-brand-new-passphrase"},
        format="json",
    )
    assert response.status_code == 400


def test_password_change_rejects_a_weak_password(auth_api):
    response = auth_api.post(
        reverse("auth-password"),
        {"current_password": PASSWORD, "new_password": "12345678"},
        format="json",
    )
    assert response.status_code == 400


def test_password_change_succeeds_and_takes_effect(auth_api, api, owner):
    new_password = "a-brand-new-passphrase-42"
    assert (
        auth_api.post(
            reverse("auth-password"),
            {"current_password": PASSWORD, "new_password": new_password},
            format="json",
        ).status_code
        == 204
    )
    owner.refresh_from_db()
    assert owner.check_password(new_password)
    assert (
        api.post(
            reverse("auth-login"), {"email": owner.email, "password": new_password}, format="json"
        ).status_code
        == 200
    )


def test_manager_creating_a_user_cannot_escape_their_cafe(auth_api, owner, other_cafe):
    """A café manager must not be able to plant an account in another tenant."""
    response = auth_api.post(
        reverse("user-list"),
        {
            "email": "new-staff@example.com",
            "password": "another-strong-passphrase",
            "role": "staff",
            "cafe": str(other_cafe.id),
        },
        format="json",
    )
    assert response.status_code == 201
    created = User.objects.get(email="new-staff@example.com")
    assert created.cafe_id == owner.cafe_id


def test_staff_role_cannot_create_users(api, staff):
    from rest_framework_simplejwt.tokens import RefreshToken

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(staff).access_token}")
    response = api.post(
        reverse("user-list"),
        {"email": "x@example.com", "password": "strong-passphrase-1", "role": "staff"},
        format="json",
    )
    assert response.status_code == 403


def test_user_list_is_scoped_to_the_callers_cafe(auth_api, other_cafe):
    User.objects.create_user(
        email="outsider@example.com", password=PASSWORD, role="staff", cafe=other_cafe
    )
    emails = {item["email"] for item in auth_api.get(reverse("user-list")).json()["results"]}
    assert "outsider@example.com" not in emails


def test_a_user_cannot_deactivate_themselves(auth_api, owner):
    response = auth_api.post(reverse("user-deactivate", args=[owner.pk]))
    assert response.status_code == 400
    owner.refresh_from_db()
    assert owner.is_active


def test_owner_can_reset_a_staff_members_password(auth_api, owner, staff, api):
    response = auth_api.post(reverse("user-reset-password", args=[staff.pk]))
    assert response.status_code == 200
    new_password = response.json()["password"]
    assert new_password and new_password != PASSWORD

    # The generated password actually works, and the old one no longer does.
    login = api.post(
        reverse("auth-login"), {"email": staff.email, "password": new_password}, format="json"
    )
    assert login.status_code == 200
    old_login = api.post(
        reverse("auth-login"), {"email": staff.email, "password": PASSWORD}, format="json"
    )
    assert old_login.status_code == 401


def test_staff_role_cannot_reset_a_password(api, staff):
    from rest_framework_simplejwt.tokens import RefreshToken

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(staff).access_token}")
    response = api.post(reverse("user-reset-password", args=[staff.pk]))
    assert response.status_code == 403


def test_a_manager_cannot_reset_a_password_for_another_cafes_staff(auth_api, other_cafe):
    outsider = User.objects.create_user(
        email="outsider2@example.com", password=PASSWORD, role="staff", cafe=other_cafe
    )
    response = auth_api.post(reverse("user-reset-password", args=[outsider.pk]))
    assert response.status_code == 404


def test_login_is_rate_limited(api, owner, monkeypatch):
    """Brute force protection: a café is on a LAN anyone in the room can join."""
    from django.core.cache import cache
    from rest_framework.throttling import ScopedRateThrottle

    # The rate lives on the throttle class, which reads settings once at import;
    # patching the class is what actually changes behaviour at runtime.
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "login", "3/min")
    cache.clear()
    try:
        for _ in range(3):
            api.post(reverse("auth-login"), {"email": owner.email, "password": "no"}, format="json")
        blocked = api.post(
            reverse("auth-login"), {"email": owner.email, "password": PASSWORD}, format="json"
        )
        assert blocked.status_code == 429
    finally:
        cache.clear()


# --------------------------------------------------------------------------- #
# the bootstrap superuser (regression: see apps.core.viewsets.CafeScopedCreateMixin)
# --------------------------------------------------------------------------- #
def test_the_bootstrap_superuser_can_create_staff_without_naming_their_cafe(
    superuser_auth_api, superuser_owner
):
    """This is the account `manage.py bootstrap` creates on every fresh
    install. Before CafeScopedCreateMixin, `perform_create`'s superuser branch
    called `serializer.save()` with no café at all -- User.cafe is nullable,
    so this did not crash, it silently created an orphaned, café-less staff
    account instead. Caught only by using this exact account shape rather
    than a plain non-superuser fixture."""
    response = superuser_auth_api.post(
        reverse("user-list"),
        {"email": "new-staff@example.com", "password": "another-strong-passphrase", "role": "staff"},
        format="json",
    )
    assert response.status_code == 201
    created = User.objects.get(email="new-staff@example.com")
    assert created.cafe_id == superuser_owner.cafe_id


def test_a_superuser_can_still_target_a_different_cafe_explicitly(superuser_auth_api, other_cafe):
    response = superuser_auth_api.post(
        reverse("user-list"),
        {
            "email": "new-staff@example.com",
            "password": "another-strong-passphrase",
            "role": "staff",
            "cafe": str(other_cafe.id),
        },
        format="json",
    )
    assert response.status_code == 201
    assert User.objects.get(email="new-staff@example.com").cafe_id == other_cafe.id
