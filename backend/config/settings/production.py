"""Production settings for an on-premise café server.

Deliberately does NOT assume TLS-terminating infrastructure: many cafés run this
on a mini PC reachable only over the shop LAN. Flip SECURE_SSL_* on via env once
a reverse proxy with a certificate is in front.
"""
from __future__ import annotations

import warnings

from config.env import ImproperlyConfigured, env_bool, env_str

from .base import *  # noqa: F401,F403
from .base import CACHE_BACKEND, CREDENTIALS_ENCRYPTION_KEY, ENVIRONMENT, SECRET_KEY

DEBUG = False

if SECRET_KEY in {"", "insecure-development-key"} or SECRET_KEY.startswith("change-me"):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a unique value in production. "
        "Generate one with `python scripts/generate_keys.py`."
    )

# The same key signs the JWTs. HS256 with a key shorter than the digest weakens
# the signature (RFC 7518 §3.2), and PyJWT warns about it at runtime rather than
# refusing -- so refuse here, where it is still fixable.
if len(SECRET_KEY.encode()) < 32:
    raise ImproperlyConfigured(
        f"DJANGO_SECRET_KEY is {len(SECRET_KEY.encode())} bytes; at least 32 are "
        "required because it also signs access tokens (HS256)."
    )

if not CREDENTIALS_ENCRYPTION_KEY:
    warnings.warn(
        "CREDENTIALS_ENCRYPTION_KEY is not set: RTSP passwords will be stored "
        "unencrypted. Generate one with "
        "`python -c \"from cryptography.fernet import Fernet; "
        "print(Fernet.generate_key().decode())\"`.",
        RuntimeWarning,
        stacklevel=1,
    )

if CACHE_BACKEND == "locmem":
    raise ImproperlyConfigured(
        "CACHE_BACKEND=locmem is a development-only setting: login throttling "
        "would be per-process and therefore trivially bypassed. Use Redis."
    )

# TLS is opt-in because a LAN-only deployment has no certificate. Turn these on
# together with a reverse proxy (see deployment/nginx/).
BEHIND_TLS_PROXY = env_bool("BEHIND_TLS_PROXY", False)
if BEHIND_TLS_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

else:
    # A LAN-only install has no certificate, so these warnings from
    # `manage.py check --deploy` are the expected state rather than findings.
    # Silencing them conditionally keeps the deploy check useful: anything it
    # does report on such an install is a genuine problem.
    SILENCED_SYSTEM_CHECKS = [
        "security.W004",  # SECURE_HSTS_SECONDS
        "security.W008",  # SECURE_SSL_REDIRECT
        "security.W012",  # SESSION_COOKIE_SECURE
        "security.W016",  # CSRF_COOKIE_SECURE
    ]

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # the dashboard reads it to set the X-CSRFToken header
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# --------------------------------------------------------------------------- #
# Error tracking (Phase 10) -- strictly opt-in
# --------------------------------------------------------------------------- #
# `sentry-sdk` is a prod dependency, but a café is local-first (spec §16): it
# must keep working, and must not phone home, with no internet at all. Unset
# SENTRY_DSN (the default) makes this block a no-op -- nothing is imported,
# nothing is contacted. A venue with internet access can opt in for crash
# visibility by setting one env var.
SENTRY_DSN = env_str("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=ENVIRONMENT,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        # Errors only -- no request/performance tracing by default. A venue
        # that wants tracing can raise this via SENTRY_TRACES_SAMPLE_RATE;
        # the default stays at the minimum this integration can report.
        traces_sample_rate=float(env_str("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        send_default_pii=False,
        # This product's whole premise is anonymous tracking (spec §26). A
        # stack frame's local variables can hold an RTSP URL or a raw request
        # body -- exactly the shapes RedactSecretsFilter exists to keep out of
        # our own logs (apps/core/logging.py). Sentry's own capture path does
        # not go through that filter, so the safer choice is to never let it
        # collect local variables at all, rather than trying to re-scrub a
        # second data shape headed to a third party.
        include_local_variables=False,
    )
