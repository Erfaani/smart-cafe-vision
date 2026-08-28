"""Test settings.

Uses in-memory/locmem backends so the suite runs without Redis, and keeps the
database configurable so CI can point at PostgreSQL while a laptop can use
sqlite (DATABASE_URL=sqlite:///test.sqlite3).
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ["*", "testserver"]

# Long enough for HS256, so the suite exercises the same signing path as
# production instead of emitting a key-length warning on every login.
SECRET_KEY = "test-secret-key-long-enough-for-hs256-signing-0123456789"

# SIMPLE_JWT captured the base SECRET_KEY at import time, so overriding the key
# above is not enough on its own -- the signing key has to follow it.
SIMPLE_JWT = {**globals()["SIMPLE_JWT"], "SIGNING_KEY": SECRET_KEY}

# Plain static storage: the manifest backend requires a collectstatic run, which
# a test suite should not depend on.
STORAGES = {
    **globals()["STORAGES"],
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

CELERY_TASK_ALWAYS_EAGER = True

# Fast hashing: password strength is asserted by validators, not by the KDF cost.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Throttles stay wired (ScopedRateThrottle errors on an unknown scope) but are
# raised out of the way; the throttle test lowers them with override_settings.
REST_FRAMEWORK = {
    **globals()["REST_FRAMEWORK"],
    "DEFAULT_THROTTLE_RATES": {"login": "1000/min", "token_refresh": "1000/min"},
}

CREDENTIALS_ENCRYPTION_KEY = "0S7hSHiA4-p6xHYCw3nMV8-K9mFqUu3dJxwbn1kQvbo="
AI_WORKER_TOKEN = "test-worker-token"
