"""Tiny, dependency-free environment parsing helpers.

Deliberately not a third-party settings library: a café install is debugged by
whoever is on site, and a stack trace that points at plain `os.environ` reads
better than one that points into a config framework.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

TRUTHY = {"1", "true", "yes", "on"}
FALSY = {"0", "false", "no", "off"}


class ImproperlyConfigured(Exception):
    """Raised when a required environment variable is missing or unusable."""


def env_str(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, "")
    if not value:
        if required and default is None:
            raise ImproperlyConfigured(f"Environment variable {name!r} is required.")
        return default or ""
    return value


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in TRUTHY:
        return True
    if raw in FALSY:
        return False
    raise ImproperlyConfigured(f"{name}={raw!r} is not a boolean value.")


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name}={raw!r} is not an integer.") from exc


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def database_config(base_dir: Path) -> dict[str, object]:
    """Build Django's DATABASES['default'] from env.

    `DATABASE_URL` wins when set; otherwise the discrete POSTGRES_* variables are
    used. sqlite is supported for lightweight development only -- production
    deployments must use PostgreSQL (see docs/architecture.md).
    """
    url = env_str("DATABASE_URL")
    if url:
        parsed = urlparse(url)
        if parsed.scheme.startswith("sqlite"):
            name = parsed.path.lstrip("/") or "db.sqlite3"
            return {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": str(base_dir / name) if not Path(name).is_absolute() else name,
            }
        if not parsed.scheme.startswith("post"):
            raise ImproperlyConfigured(
                f"Unsupported DATABASE_URL scheme {parsed.scheme!r}; "
                "use postgres:// or sqlite://"
            )
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
            "CONN_MAX_AGE": 60,
        }

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_str("POSTGRES_DB", "smartcafe"),
        "USER": env_str("POSTGRES_USER", "smartcafe"),
        "PASSWORD": env_str("POSTGRES_PASSWORD", "smartcafe"),
        "HOST": env_str("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env_str("POSTGRES_PORT", "5432"),
        # Persistent connections: the AI event ingest path is chatty and
        # per-request connection setup shows up in latency on a mini PC.
        "CONN_MAX_AGE": 60,
    }
