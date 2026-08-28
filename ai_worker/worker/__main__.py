"""Entrypoint: `python -m worker`."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:  # pragma: no cover - dotenv is optional
    pass

from worker.runner import main

if __name__ == "__main__":
    sys.exit(main())
