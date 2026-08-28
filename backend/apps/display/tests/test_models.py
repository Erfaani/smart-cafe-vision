from __future__ import annotations

import pytest

from apps.display.models import DisplayMessage

pytestmark = pytest.mark.django_db


def make_message(cafe, **overrides) -> DisplayMessage:
    defaults = {"cafe": cafe, "text_en": "Enjoy your coffee!"}
    defaults.update(overrides)
    return DisplayMessage.objects.create(**defaults)


def test_text_returns_english_by_default(cafe):
    message = make_message(cafe, text_en="Hello", text_fa="سلام")
    assert message.text("en") == "Hello"


def test_text_returns_persian_when_translated(cafe):
    message = make_message(cafe, text_en="Hello", text_fa="سلام")
    assert message.text("fa") == "سلام"


def test_text_falls_back_to_english_when_untranslated(cafe):
    """An empty text_fa would render as a blank line on the display -- the
    wrong language reads better than nothing at all."""
    message = make_message(cafe, text_en="Hello", text_fa="")
    assert message.text("fa") == "Hello"
