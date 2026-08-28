"""Shared Django settings for Smart Café Vision.

Environment-specific modules (development, production, test) import from here
and override only what genuinely differs.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from config.env import database_config, env_bool, env_int, env_list, env_str

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent

# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
SECRET_KEY = env_str("DJANGO_SECRET_KEY", "insecure-development-key")
DEBUG = env_bool("DJANGO_DEBUG", False)
ENVIRONMENT = env_str("ENVIRONMENT", "development")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    # daphne must precede staticfiles: it swaps runserver for an ASGI server
    # so websockets work in development exactly as they do in production.
    "daphne",
    "channels",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    # Local
    "apps.core",
    "apps.tenants",
    "apps.accounts",
    "apps.events",
    "apps.cameras",
    "apps.sessions",
    "apps.display",
    "apps.analytics",
    "apps.tables",
]

MIDDLEWARE = [
    "apps.core.middleware.RequestIDMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------- #
# Data stores
# --------------------------------------------------------------------------- #
DATABASES = {"default": database_config(BASE_DIR)}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = env_str("REDIS_URL", "redis://127.0.0.1:6379/0")

# Redis is the right cache for a real install (it is already running for the
# event bus, and login throttling must be shared across backend processes).
# `locmem` exists so a developer can run the API on a laptop with no Redis at
# all -- throttle counters are then per-process, which is fine for development
# and never acceptable in production.
CACHE_BACKEND = env_str("CACHE_BACKEND", "redis").lower()
if CACHE_BACKEND == "locmem":
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# Redis Streams event bus (AI worker -> backend). Streams, not pub/sub: a
# dropped person_exited event would corrupt stay-time analytics permanently.
EVENT_STREAM_KEY = env_str("EVENT_STREAM_KEY", "scv:events")
EVENT_STREAM_GROUP = env_str("EVENT_STREAM_GROUP", "scv-ingest")
EVENT_STREAM_MAXLEN = env_int("EVENT_STREAM_MAXLEN", 100000)

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TIME_LIMIT = 300

# How long a CustomerSession may go without evidence of the person still
# being in frame (a crossing, or a camera_stats heartbeat naming their
# track_id) before apps.sessions.tasks.close_stale_sessions ends it as
# TRACK_LOST. Several multiples of CAMERA_STATS_INTERVAL_SECONDS (worker
# default: 10s), so a couple of missed heartbeats never closes a session that
# is still genuinely open.
SESSION_STALE_GRACE_SECONDS = env_int("SESSION_STALE_GRACE_SECONDS", 120)

# Same idea as SESSION_STALE_GRACE_SECONDS, for a table whose worker went
# quiet without a clean table_released event.
TABLE_STALE_GRACE_SECONDS = env_int("TABLE_STALE_GRACE_SECONDS", 120)

# How long a raw TrackingEvent row survives before apps.events.prune_old_events
# deletes it (Phase 10, spec §16, docs/privacy.md's Retention section). Safe
# to prune: every durable figure the product reports is a projection computed
# from these rows at ingest time and stored in its own table (CustomerSession,
# TableSession, DailyStat) -- deleting an old event does not lose anything a
# café can still see, only the ability to recompute a projection for that day
# if a bug is ever found in one. 0 disables pruning.
EVENT_RETENTION_DAYS = env_int("EVENT_RETENTION_DAYS", 90)

CELERY_BEAT_SCHEDULE = {
    "close-stale-customer-sessions": {
        "task": "apps.sessions.close_stale_sessions",
        "schedule": env_int("SESSION_STALE_CHECK_INTERVAL_SECONDS", 60),
    },
    "close-stale-table-sessions": {
        "task": "apps.tables.close_stale_table_sessions",
        "schedule": env_int("TABLE_STALE_CHECK_INTERVAL_SECONDS", 60),
    },
    "refresh-daily-stats": {
        "task": "apps.analytics.refresh_daily_stats",
        "schedule": env_int("ANALYTICS_ROLLUP_INTERVAL_SECONDS", 900),
    },
    "prune-old-events": {
        "task": "apps.events.prune_old_events",
        "schedule": env_int("EVENT_PRUNE_INTERVAL_SECONDS", 86400),
    },
}

# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Argon2 first: café servers are often small mini PCs, and the default PBKDF2
# iteration count is measurably the slowest part of a login there.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("ACCESS_TOKEN_LIFETIME_MINUTES", 30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("REFRESH_TOKEN_LIFETIME_DAYS", 7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_TYPE_CLAIM": "token_type",
}

# --------------------------------------------------------------------------- #
# DRF
# --------------------------------------------------------------------------- #
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.ScopedRateThrottle",),
    "DEFAULT_THROTTLE_RATES": {"login": "10/min", "token_refresh": "60/min"},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Smart Café Vision API",
    "DESCRIPTION": (
        "Local-first computer-vision occupancy and stay-time analytics for cafés. "
        "All tracking is anonymous: no faces, names, or biometric identifiers are stored."
    ),
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

# --------------------------------------------------------------------------- #
# CORS / CSRF
# --------------------------------------------------------------------------- #
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", ["http://localhost:3000"])
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS", ["http://localhost:3000", "http://localhost:8000"]
)
FRONTEND_ORIGIN = env_str("FRONTEND_ORIGIN", "http://localhost:3000")

# --------------------------------------------------------------------------- #
# i18n / time - every duration in this product is computed from UTC timestamps
# --------------------------------------------------------------------------- #
LANGUAGE_CODE = "en-us"
LANGUAGES = [("en", "English"), ("fa", "Persian")]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------- #
# Static / media
# --------------------------------------------------------------------------- #
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "mediafiles"

# --------------------------------------------------------------------------- #
# Privacy and security knobs (spec sections 25, 26)
# --------------------------------------------------------------------------- #
# Fernet key protecting RTSP passwords at rest. Empty means credentials are
# stored in plaintext and the system logs a loud warning at startup.
CREDENTIALS_ENCRYPTION_KEY = env_str("CREDENTIALS_ENCRYPTION_KEY", "")

# Raw video is never persisted unless an administrator explicitly turns it on.
ALLOW_VIDEO_RECORDING = env_bool("ALLOW_VIDEO_RECORDING", False)

# Shared secret the AI worker presents on the ingest API.
AI_WORKER_TOKEN = env_str("AI_WORKER_TOKEN", "")

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# --------------------------------------------------------------------------- #
# Logging (spec section 28) - structured, and scrubbed of credentials
# --------------------------------------------------------------------------- #
LOG_LEVEL = env_str("DJANGO_LOG_LEVEL", "INFO").upper()
LOG_FORMAT = env_str("DJANGO_LOG_FORMAT", "console").lower()
if LOG_FORMAT not in {"console", "json"}:
    LOG_FORMAT = "console"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "apps.core.logging.RequestIDFilter"},
        "redact_secrets": {"()": "apps.core.logging.RedactSecretsFilter"},
    },
    "formatters": {
        "console": {
            "format": "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s",
        },
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT,
            "filters": ["request_id", "redact_secrets"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "smartcafe": {"level": LOG_LEVEL, "handlers": ["console"], "propagate": False},
    },
}
