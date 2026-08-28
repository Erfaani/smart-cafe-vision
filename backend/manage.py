#!/usr/bin/env python
"""Django management entrypoint for Smart Café Vision."""
import os
import sys
from pathlib import Path


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

    # Load the repository-root .env so `manage.py` behaves the same in and out
    # of Docker. Docker Compose injects the same variables via `env_file`.
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:  # pragma: no cover - dotenv is optional at runtime
        pass

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Couldn't import Django. Is it installed and is your virtualenv active?"
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
