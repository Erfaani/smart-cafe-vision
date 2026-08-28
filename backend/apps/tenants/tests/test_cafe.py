from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse

from apps.tenants.models import Cafe, validate_logo_size

pytestmark = pytest.mark.django_db


def test_slug_is_generated_from_the_name():
    cafe = Cafe.objects.create(name="Café del Mar")
    assert cafe.slug == "cafe-del-mar"


def test_duplicate_names_get_distinct_slugs():
    first = Cafe.objects.create(name="Roasters")
    second = Cafe.objects.create(name="Roasters")
    assert first.slug != second.slug
    assert second.slug == "roasters-2"


def test_privacy_notice_follows_the_language():
    cafe = Cafe.objects.create(name="Test", default_language="fa")
    assert cafe.privacy_notice() == cafe.privacy_notice_fa
    assert cafe.privacy_notice("en") == cafe.privacy_notice_en


def test_public_endpoint_exposes_branding_only(api, cafe):
    response = api.get(reverse("public-cafe", args=[cafe.slug]))
    assert response.status_code == 200
    body = response.json()
    # Exactly the fields the TV in the corner needs, and nothing more.
    # stay_color_stops (Phase 6) and seating_capacity (Phase 7) are
    # deliberate, documented exceptions -- see PublicCafeSerializer's
    # docstring for why each is safe to expose unauthenticated.
    assert set(body) == {
        "name", "slug", "logo", "default_language", "privacy_notice",
        "stay_color_stops", "seating_capacity",
    }
    assert "is_active" not in body


def test_public_endpoint_hides_a_deactivated_cafe(api, cafe):
    cafe.is_active = False
    cafe.save(update_fields=["is_active"])
    assert api.get(reverse("public-cafe", args=[cafe.slug])).status_code == 404


def test_cafe_api_requires_authentication(api, cafe):
    assert api.get(reverse("cafe-list")).status_code == 401


def test_cafe_list_is_scoped_to_the_callers_cafe(auth_api, cafe, other_cafe):
    slugs = {item["slug"] for item in auth_api.get(reverse("cafe-list")).json()["results"]}
    assert slugs == {cafe.slug}


def test_invalid_timezone_is_rejected(auth_api, cafe):
    response = auth_api.patch(
        reverse("cafe-detail", args=[cafe.slug]), {"timezone": "Mars/Olympus"}, format="json"
    )
    assert response.status_code == 400


def test_valid_timezone_is_accepted(auth_api, cafe):
    response = auth_api.patch(
        reverse("cafe-detail", args=[cafe.slug]), {"timezone": "Asia/Tehran"}, format="json"
    )
    assert response.status_code == 200
    cafe.refresh_from_db()
    assert cafe.timezone == "Asia/Tehran"


# --------------------------------------------------------------------------- #
# stay_color_stops (Phase 6)
# --------------------------------------------------------------------------- #
def test_a_new_cafe_gets_the_default_traffic_light_stops():
    cafe = Cafe.objects.create(name="Fresh")
    assert cafe.stay_color_stops[0] == {"seconds": 0, "color": "#22c55e"}
    assert cafe.stay_color_stops[-1]["color"] == "#ef4444"


def test_stay_color_stops_can_be_reconfigured_through_the_api(auth_api, cafe):
    new_stops = [
        {"seconds": 0, "color": "#0000ff"},
        {"seconds": 600, "color": "#ff0000"},
    ]
    response = auth_api.patch(
        reverse("cafe-detail", args=[cafe.slug]), {"stay_color_stops": new_stops}, format="json"
    )
    assert response.status_code == 200
    cafe.refresh_from_db()
    assert cafe.stay_color_stops == new_stops


def test_malformed_stay_color_stops_are_rejected_by_the_api(auth_api, cafe):
    response = auth_api.patch(
        reverse("cafe-detail", args=[cafe.slug]),
        {"stay_color_stops": [{"seconds": 5, "color": "#22c55e"}, {"seconds": 10, "color": "#ef4444"}]},
        format="json",
    )
    assert response.status_code == 400
    cafe.refresh_from_db()
    assert cafe.stay_color_stops[0]["seconds"] == 0  # unchanged


# --------------------------------------------------------------------------- #
# Logo upload size cap (Phase 10 -- production hardening)
# --------------------------------------------------------------------------- #
def test_a_logo_within_the_size_limit_is_accepted():
    small = SimpleUploadedFile("logo.png", b"x" * 1024, content_type="image/png")
    validate_logo_size(small)  # does not raise


def test_a_logo_over_the_size_limit_is_rejected():
    oversized = SimpleUploadedFile(
        "logo.png", b"x" * (5 * 1024 * 1024 + 1), content_type="image/png"
    )
    with pytest.raises(ValidationError, match="smaller than 5 MB"):
        validate_logo_size(oversized)


# --------------------------------------------------------------------------- #
# bootstrap command
# --------------------------------------------------------------------------- #
def test_bootstrap_creates_a_cafe_and_owner(capsys):
    call_command("bootstrap", "--email=owner@cafe.test", "--cafe-name=Bootstrapped")

    cafe = Cafe.objects.get(name="Bootstrapped")
    from django.contrib.auth import get_user_model

    owner = get_user_model().objects.get(email="owner@cafe.test")
    assert owner.cafe_id == cafe.id
    assert owner.role == "owner" and owner.is_superuser
    # A generated password is printed exactly once so the installer can save it.
    assert "Password:" in capsys.readouterr().out


def test_bootstrap_is_idempotent():
    """A technician re-running the installer must not create a second café."""
    call_command("bootstrap", "--email=owner@cafe.test", "--cafe-name=Bootstrapped")
    call_command("bootstrap", "--email=owner@cafe.test", "--cafe-name=Bootstrapped")

    assert Cafe.objects.filter(name="Bootstrapped").count() == 1

    from django.contrib.auth import get_user_model

    assert get_user_model().objects.filter(email="owner@cafe.test").count() == 1


def test_bootstrap_does_not_reset_an_existing_password():
    call_command("bootstrap", "--email=owner@cafe.test", "--password=first-password-1")

    from django.contrib.auth import get_user_model

    call_command("bootstrap", "--email=owner@cafe.test", "--password=second-password-2")
    owner = get_user_model().objects.get(email="owner@cafe.test")
    assert owner.check_password("first-password-1")
