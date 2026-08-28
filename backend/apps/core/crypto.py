"""Symmetric encryption for stored camera credentials (spec §25).

RTSP passwords must survive a database dump landing in the wrong hands. They are
encrypted with Fernet using CREDENTIALS_ENCRYPTION_KEY, which lives in the
environment and never in the database.

If no key is configured the system stays usable but stores credentials in the
clear and says so loudly -- silently degrading security would be worse.
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger("smartcafe.security")

_PLAINTEXT_PREFIX = "plain:"
_ENCRYPTED_PREFIX = "fernet:"


def _fernet():
    key = settings.CREDENTIALS_ENCRYPTION_KEY
    if not key:
        return None
    from cryptography.fernet import Fernet

    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_secret(value: str) -> str:
    """Encrypt a secret for storage. Returns a prefixed, self-describing string."""
    if not value:
        return ""
    fernet = _fernet()
    if fernet is None:
        logger.warning(
            "CREDENTIALS_ENCRYPTION_KEY is unset; storing a camera credential "
            "in plaintext. Set the key and re-save the camera."
        )
        return f"{_PLAINTEXT_PREFIX}{value}"
    return f"{_ENCRYPTED_PREFIX}{fernet.encrypt(value.encode()).decode()}"


def decrypt_secret(stored: str) -> str:
    """Reverse of encrypt_secret. Tolerates values written before a key existed."""
    if not stored:
        return ""
    if stored.startswith(_PLAINTEXT_PREFIX):
        return stored[len(_PLAINTEXT_PREFIX):]
    if not stored.startswith(_ENCRYPTED_PREFIX):
        # Legacy/unprefixed value: treat as plaintext rather than crashing a
        # camera stream at 3am.
        return stored
    fernet = _fernet()
    if fernet is None:
        raise RuntimeError(
            "A stored credential is encrypted but CREDENTIALS_ENCRYPTION_KEY is "
            "not configured. Restore the key to read camera credentials."
        )
    from cryptography.fernet import InvalidToken

    try:
        return fernet.decrypt(stored[len(_ENCRYPTED_PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError(
            "Stored credential could not be decrypted: CREDENTIALS_ENCRYPTION_KEY "
            "does not match the key used to write it."
        ) from exc


def is_encrypted(stored: str) -> bool:
    return stored.startswith(_ENCRYPTED_PREFIX)
