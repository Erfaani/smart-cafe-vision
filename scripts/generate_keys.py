"""Fill the placeholder secrets in `.env` with generated values.

Run once after copying `.env.example`. Idempotent: a value that has already been
generated is left alone, so re-running never invalidates existing sessions or —
much worse — makes stored camera passwords undecryptable.
"""
from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"

PLACEHOLDERS = {
    "DJANGO_SECRET_KEY": ("change-me-insecure-development-key-do-not-use-in-production", ""),
    "AI_WORKER_TOKEN": ("change-me-worker-token", ""),
    "CREDENTIALS_ENCRYPTION_KEY": ("",),
}


def generate(key: str) -> str:
    if key == "CREDENTIALS_ENCRYPTION_KEY":
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            print(
                "cryptography is not installed; skipping CREDENTIALS_ENCRYPTION_KEY.\n"
                "Install backend requirements and re-run to enable camera credential "
                "encryption.",
                file=sys.stderr,
            )
            return ""
        return Fernet.generate_key().decode()
    return secrets.token_urlsafe(48)


def main() -> int:
    if not ENV_PATH.exists():
        print(f"{ENV_PATH} not found. Copy .env.example to .env first.", file=sys.stderr)
        return 1

    content = ENV_PATH.read_text(encoding="utf-8")
    changed: list[str] = []

    for key, placeholder_values in PLACEHOLDERS.items():
        match = re.search(rf"^{key}=(.*)$", content, flags=re.MULTILINE)
        if match is None:
            continue
        current = match.group(1).strip()
        if current not in placeholder_values:
            continue  # already set by a human or a previous run

        value = generate(key)
        if not value:
            continue
        content = re.sub(rf"^{key}=.*$", f"{key}={value}", content, flags=re.MULTILINE)
        changed.append(key)

    if changed:
        ENV_PATH.write_text(content, encoding="utf-8")
        print("Generated: " + ", ".join(changed))
    else:
        print("Nothing to generate; every secret already has a value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
