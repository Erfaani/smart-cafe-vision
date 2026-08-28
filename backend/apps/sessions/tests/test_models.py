from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.sessions.models import CustomerSession

pytestmark = pytest.mark.django_db


def make_session(cafe, **overrides) -> CustomerSession:
    now = timezone.now()
    defaults = {
        "cafe": cafe,
        "camera_id": uuid.uuid4(),
        "track_id": 7,
        "entry_at": now,
        "last_seen_at": now,
    }
    defaults.update(overrides)
    return CustomerSession.objects.create(**defaults)


def test_duration_seconds_for_an_ended_session_is_exit_minus_entry(cafe):
    entry = timezone.now() - timedelta(minutes=10)
    exit_ = entry + timedelta(minutes=7)
    session = make_session(cafe, entry_at=entry, exit_at=exit_, status=CustomerSession.Status.ENDED)
    assert session.duration_seconds == pytest.approx(420, abs=1)


def test_duration_seconds_for_an_active_session_counts_up_to_now(cafe):
    entry = timezone.now() - timedelta(minutes=5)
    session = make_session(cafe, entry_at=entry)
    assert session.duration_seconds == pytest.approx(300, abs=2)


def test_default_status_is_active(cafe):
    session = make_session(cafe)
    assert session.status == CustomerSession.Status.ACTIVE
    assert session.exit_at is None


def test_track_id_is_not_unique_across_sessions(cafe):
    """Deliberately allowed: the same track_id is reused by a fresh AI worker
    process, or even within one process's lifetime after a track is dropped
    and a new person is assigned the same small integer."""
    make_session(cafe, track_id=1)
    make_session(cafe, track_id=1)  # must not raise
    assert CustomerSession.objects.filter(track_id=1).count() == 2


# --------------------------------------------------------------------------- #
# color (Phase 6)
# --------------------------------------------------------------------------- #
def test_color_is_the_first_stop_for_a_fresh_session(cafe):
    session = make_session(cafe, entry_at=timezone.now())
    assert session.color == cafe.stay_color_stops[0]["color"]


def test_color_follows_the_cafes_configured_stops(cafe):
    cafe.stay_color_stops = [
        {"seconds": 0, "color": "#0000ff"},
        {"seconds": 100, "color": "#ff0000"},
    ]
    cafe.save(update_fields=["stay_color_stops"])
    session = make_session(cafe, entry_at=timezone.now() - timedelta(seconds=100))
    assert session.color == "#ff0000"


def test_color_for_an_ended_session_is_fixed_at_its_exit_duration(cafe):
    cafe.stay_color_stops = [
        {"seconds": 0, "color": "#0000ff"},
        {"seconds": 100, "color": "#ff0000"},
    ]
    cafe.save(update_fields=["stay_color_stops"])
    entry = timezone.now() - timedelta(hours=2)
    session = make_session(
        cafe, entry_at=entry, exit_at=entry + timedelta(seconds=100), status=CustomerSession.Status.ENDED
    )
    # Long since ended: colour must reflect the 100s stay it actually had, not
    # how long ago that was.
    assert session.color == "#ff0000"
