"""Development settings: verbose, permissive, still local-first."""
from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import DATABASES, ENVIRONMENT  # noqa: F401

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Let a developer hit the dashboard from another device on the same LAN
# (phones, the café TV) without editing settings.
CORS_ALLOW_ALL_ORIGINS = True

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
