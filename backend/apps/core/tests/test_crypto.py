"""Camera credential encryption at rest (spec §25)."""
from __future__ import annotations

import pytest

from apps.core.crypto import decrypt_secret, encrypt_secret, is_encrypted


def test_secret_round_trips(settings):
    stored = encrypt_secret("hunter2")
    assert is_encrypted(stored)
    assert "hunter2" not in stored, "the plaintext must not survive in the column"
    assert decrypt_secret(stored) == "hunter2"


def test_encryption_is_not_deterministic(settings):
    """Two cameras sharing a password must not produce identical ciphertext."""
    assert encrypt_secret("hunter2") != encrypt_secret("hunter2")


def test_empty_secret_stays_empty(settings):
    assert encrypt_secret("") == ""
    assert decrypt_secret("") == ""


def test_without_a_key_the_value_is_stored_readably_and_flagged(settings):
    settings.CREDENTIALS_ENCRYPTION_KEY = ""
    stored = encrypt_secret("hunter2")
    assert not is_encrypted(stored)
    assert decrypt_secret(stored) == "hunter2"


def test_a_wrong_key_fails_loudly_instead_of_returning_garbage(settings):
    from cryptography.fernet import Fernet

    stored = encrypt_secret("hunter2")
    settings.CREDENTIALS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with pytest.raises(RuntimeError, match="does not match"):
        decrypt_secret(stored)


def test_a_legacy_unprefixed_value_is_read_as_plaintext(settings):
    """An upgrade must not take every camera offline."""
    assert decrypt_secret("legacy-plaintext") == "legacy-plaintext"
